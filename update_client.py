#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from git import Repo
import json
from io import BytesIO
import subprocess
import shutil
import time
import hashlib
import base64
import zipfile
import shutil
import re

def ensure_dir(dir):
    if not os.path.exists(dir):
        os.makedirs(dir)

def recreate_dir(dir):
    if os.path.exists(dir):
        shutil.rmtree(dir)
        os.makedirs(dir)
    else:
        os.makedirs(dir)

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.realpath(__file__))

    #if len(sys.argv) < 2:
    #    print("Please specify folder as input arguments")
    #    exit()

    branch = "main"
    repo_dir = os.path.join("/home/Launcher/patcher/gitclient/")
    pub_dir = os.path.join(script_dir, 'files', 'client')

    file_filters = [r"\/{0,1}\.gitignore", r"animation/.+\.lab.+"]

    # Pare arguments
    doPull = "--pull" in sys.argv
    dry_run = '--dry-run' in sys.argv
    force = "--force" in sys.argv
    print("Branch: {}".format(branch))
    
    # Prepare folders
    contents_dir = os.path.join(pub_dir, 'versions_data')
    version_file = os.path.join(pub_dir, 'version.json')

    # Read available versions
    content = {}
    with open(version_file, 'rt') as json_file:
        content = json.load(json_file)
    base_hash = content["base_hash"]
    print("Base hash: {}".format(base_hash))
    patches = []
    if "patches" in content.keys():
    	patches = content["patches"]
    if force:
        patches = content["patches"] = []

    # Update base checksum if need
#    if not "base_checksum" in content.keys():
    print("Calculating base client checksum...")
    need_to_unpack_base = False
    base_file = os.path.join(pub_dir, content["base_archive"])
    with open(base_file, "rb") as file:
        sha = hashlib.sha256()
        for block in iter(lambda: file.read(4096), b""):
            sha.update(block)
        crc = base64.b64encode(sha.digest()).decode("utf-8")
        if ("base_checksum" in content) and (content["base_checksum"] != crc):
            need_to_unpack_base = True
        if not ("base_checksum" in content):
            need_to_unpack_base = True
        content["base_checksum"] = crc
        print('Base client checksum is {}'.format(content["base_checksum"]))
    base_dir = os.path.join(pub_dir, os.path.splitext(content["base_archive"])[0])
    if not os.path.exists(base_dir):
        need_to_unpack_base = True
    
    if need_to_unpack_base:
        print('Unpacking base client...')
        ensure_dir(base_dir)
        shutil.unpack_archive(base_file, extract_dir=base_dir)
        
        
    
    print("repo_dir {}" .format(repo_dir))
    # Initialize repo
    repo = Repo(repo_dir)
    # repo.config_writer().set_value('core', 'quotepath', 'true').release()
    
    if doPull:
        print("Pulling branch {}...".format(branch))
        if not dry_run: repo.remotes.origin.pull(branch)
    
    all_commits = list(repo.iter_commits(branch, encoding="utf-8"))
    all_commits.reverse()
    working_commits_ind = list(map(lambda c: c.hexsha, all_commits)).index(base_hash) + 1
    working_commits = all_commits[working_commits_ind : ]
    print("Total commits: {}, working commits: {} from index {}".format(len(all_commits), len(working_commits), working_commits_ind))
    new_commits = list(working_commits)
    diff_commit = all_commits[working_commits_ind - 1]

    if len(patches) > 0:
        last_known_ind = list(map(lambda c: c.hexsha, all_commits)).index(patches[-1]["hash"])
        new_commits = all_commits[last_known_ind + 1:]
        diff_commit = all_commits[last_known_ind]
    print("{} new commits found".format(len(new_commits)))
    
    #if len(new_commits) == 0:
    #    exit(0)

    for commit in new_commits:
        print("Processing commit {}...".format(commit.hexsha))
        diffs = diff_commit.diff(commit)
        
        # Add patch record
        changes = []
        patch = {
            "hash": commit.hexsha,
            "message": commit.message,
            "changes": changes
        }
        for diff in diffs:
            # Process files filter
            do_skip = False
            for path in [diff.a_path, diff.b_path]:
                for filt in file_filters:
                    if re.search(filt, path):
                        do_skip = True

            if do_skip:
                continue

            if diff.change_type in ["A", "M", "D"]:
                changes.append({
                    "type": diff.change_type,
                    "path": diff.a_path
                })
            elif diff.change_type in ["R"]:
                changes.append({
                    "type": "D",
                    "path": diff.a_path
                })
                changes.append({
                    "type": "A",
                    "path": diff.b_path
                })

        # Generate patch content
        patch_dir = os.path.join(contents_dir, '{}_{}'.format(diff_commit.hexsha, commit.hexsha))
        if not dry_run: recreate_dir(patch_dir)
        for change in filter(lambda c: c["type"] in ["A", "M"], changes):
            repo_file = change["path"]
            out_file = os.path.join(patch_dir, repo_file)
          
            print("git -c \"{}\" show {}:\"{}\" > \"{}\"".format(repo_dir, commit.hexsha, repo_file, out_file))
            cmd = "git -c \"{}\" show {}:\"{}\" > \"{}\"".format(repo_dir, commit.hexsha, repo_file, out_file)
            #cmd = "git -c \"{}{}\" > \"{}\"" . format(repo_dir, repo_file, out_file)
            
            if not dry_run: 
                ensure_dir(os.path.dirname(out_file))
                os.system(cmd)
                change["size"] = os.path.getsize(out_file)
                # Calculating file checksum
                with open(out_file, "rb") as file:
                    sha = hashlib.sha256()
                    for block in iter(lambda: file.read(4096), b""):
                        sha.update(block)
                    change["checksum"] = base64.b64encode(sha.digest()).decode("utf-8")

        # Generate patch archive
        patch_archive = os.path.join(contents_dir, '{}_{}.zip'.format(diff_commit.hexsha, commit.hexsha))
        shutil.make_archive(patch_dir, 'zip', patch_dir)
        patch["archive"] = os.path.basename(patch_archive)
        patch["archive_size"] = os.path.getsize(patch_archive)
        with open(patch_archive, 'rb') as file:
            sha = hashlib.sha256()
            for block in iter(lambda: file.read(4096), b""):
                sha.update(block)
            patch["archive_checksum"] = base64.b64encode(sha.digest()).decode("utf-8")

        diff_commit = commit
        
        patches.append(patch)

    # Generate new versions file using atomic (not really atomic) replace
    if not dry_run:
        version_tmp = version_file + "~"
        with open(version_tmp, 'w') as file:
            json.dump(content, file, indent=4, ensure_ascii=False)
        os.replace(version_tmp, version_file)

    print("Nicely done!")
