#!/usr/bin/env python3
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only

"""Exercise three persistent test accounts in a private group, including media."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://matrix.547626.xyz"
PRIVATE = Path("/opt/radish-chat/private")


def request(method, path, data=None, token=None, content_type="application/json"):
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = json.dumps(data).encode() if isinstance(data, dict) else data
    base = "http://127.0.0.1:8008" if path.startswith("/_synapse/admin/") else BASE
    for attempt in range(4):
        try:
            with urlopen(Request(base + path, data=payload, headers=headers, method=method), timeout=30) as response:
                body = response.read()
                return json.loads(body) if "json" in response.headers.get("Content-Type", "") else body
        except HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise
            delay = json.load(error).get("retry_after_ms", 10000) / 1000
            time.sleep(delay + 1)


def register(username, password, admin=False):
    shared_secret = json.loads((PRIVATE / "server-secrets.json").read_text())["registration_secret"]
    local = "http://127.0.0.1:8008/_synapse/admin/v1/register"
    with urlopen(local, timeout=10) as response:
        nonce = json.load(response)["nonce"]
    message = "\0".join((nonce, username, password, "admin" if admin else "notadmin"))
    signature = hmac.new(shared_secret.encode(), message.encode(), hashlib.sha1).hexdigest()
    data = json.dumps({
        "nonce": nonce, "username": username, "password": password,
        "admin": admin, "mac": signature,
    }).encode()
    with urlopen(Request(local, data=data, headers={"Content-Type": "application/json"}), timeout=20) as response:
        return json.load(response)


def main():
    os.umask(0o077)
    admin_file = PRIVATE / "admin.json"
    if not admin_file.exists():
        admin_file.write_text(json.dumps({
            "username": "radish", "user_id": "@radish:547626.xyz",
            "password": secrets.token_urlsafe(24), "url": "https://chat.547626.xyz",
        }, indent=4) + "\n")
    admin = json.loads(admin_file.read_text())
    try:
        register(admin["username"], admin["password"], admin=True)
    except HTTPError as error:
        if json.load(error).get("errcode") != "M_USER_IN_USE":
            raise
    probe = secrets.token_hex(4)
    owner = register("deployprobe_admin_" + probe, secrets.token_urlsafe(24), admin=True)
    owner_token = owner["access_token"]
    previous = request("GET", "/_synapse/admin/v2/users?name=deployprobe_&limit=100", token=owner_token)
    for account in previous["users"]:
        if re.fullmatch(r"@deployprobe_[ab]_[0-9a-f]{8}:547626.xyz", account["name"]):
            request("POST", "/_synapse/admin/v1/deactivate/" + quote(account["name"], safe=""),
                    {"erase": True}, owner_token)
    accounts_file = PRIVATE / "test-accounts.json"
    if not accounts_file.exists():
        accounts_file.write_text(json.dumps({
            "url": "https://chat.547626.xyz", "group_name": "部署验收群",
            "users": [{"username": name, "password": secrets.token_urlsafe(24)}
                      for name in ("test_alice", "test_bob", "test_carol")],
        }, indent=4, ensure_ascii=False) + "\n")
    accounts = json.loads(accounts_file.read_text())
    sessions = []
    try:
        for account in accounts["users"]:
            try:
                session = register(account["username"], account["password"])
            except HTTPError as error:
                if json.load(error).get("errcode") != "M_USER_IN_USE":
                    raise
                user_id = "@" + account["username"] + ":547626.xyz"
                session = request("POST", "/_synapse/admin/v1/users/" + quote(user_id, safe="") + "/login",
                                  {}, owner_token)
                session["user_id"] = user_id
            sessions.append(session)
        first, second, third = sessions
        if "room_id" not in accounts:
            accounts["room_id"] = request("POST", "/_matrix/client/v3/createRoom", {
                "name": accounts["group_name"], "preset": "private_chat",
                "invite": [second["user_id"], third["user_id"], admin["user_id"]],
            }, first["access_token"])["room_id"]
            accounts_file.write_text(json.dumps(accounts, indent=4, ensure_ascii=False) + "\n")
        room_id = accounts["room_id"]
        room = quote(room_id, safe="")
        for session in sessions:
            request("POST", "/_matrix/client/v3/join/" + room, {}, session["access_token"])
        members = request("GET", "/_matrix/client/v3/rooms/" + room + "/joined_members",
                          token=first["access_token"])["joined"]
        assert all(session["user_id"] in members for session in sessions)
        for index, sender in enumerate(sessions):
            body = "群聊验收 " + sender["user_id"] + " " + probe
            sent = request("PUT", "/_matrix/client/v3/rooms/" + room + "/send/m.room.message/" +
                           probe + str(index), {"msgtype": "m.text", "body": body}, sender["access_token"])
            for receiver in sessions:
                event = request("GET", "/_matrix/client/v3/rooms/" + room + "/event/" +
                                quote(sent["event_id"], safe=""), token=receiver["access_token"])
                assert event["content"]["body"] == body
        print("PASS three accounts joined the group; all three sent messages; all nine reads matched")
        payload = ("File verification " + probe).encode()
        uploaded = request("POST", "/_matrix/media/v3/upload?filename=verification.txt", payload,
                           second["access_token"], "text/plain")["content_uri"]
        server, media = uploaded.removeprefix("mxc://").split("/", 1)
        download = "/_matrix/client/v1/media/download/" + quote(server, safe="") + "/" + quote(media, safe="")
        sent = request("PUT", "/_matrix/client/v3/rooms/" + room + "/send/m.room.message/file-" + probe, {
            "msgtype": "m.file", "body": "verification.txt", "url": uploaded,
            "info": {"mimetype": "text/plain", "size": len(payload)},
        }, second["access_token"])
        for receiver in sessions:
            event = request("GET", "/_matrix/client/v3/rooms/" + room + "/event/" +
                            quote(sent["event_id"], safe=""), token=receiver["access_token"])
            assert event["content"]["url"] == uploaded
            assert request("GET", download, token=receiver["access_token"]) == payload
        print("PASS file shared in the group and downloaded identically by all three accounts")
    finally:
        for session in sessions:
            request("POST", "/_matrix/client/v3/logout", {}, session["access_token"])
        request("POST", "/_synapse/admin/v1/deactivate/" + quote(owner["user_id"], safe=""),
                {"erase": True}, owner_token)
    print("PASS test accounts and group retained; temporary verification tokens revoked")


if __name__ == "__main__":
    main()
