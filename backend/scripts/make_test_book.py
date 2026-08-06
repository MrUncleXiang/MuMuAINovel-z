#!/usr/bin/env python3
"""测试书工厂：一键创建"素材完整"的测试书，避免手工 API 建书漏字段。

用法（宿主机）：
  python3 make_test_book.py --title "测试书" --theme "主题" --genre "都市"
  python3 make_test_book.py --copy-from <原项目id> --chapters 10   # 从原版复制完整素材
  python3 make_test_book.py --title "测试" --theme "t" --genre "g" --pipeline 3   # 建后自动写3章

保证：description 兜底、wizard_status=completed、世界观/角色/大纲齐全。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("MUMU_BASE", "http://127.0.0.1:19000")


def login(password: str) -> urllib.request.OpenerDirector:
    import http.cookiejar

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(
        BASE + "/api/auth/local/login",
        data=json.dumps({"username": "admin", "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener.open(req, timeout=10)
    return opener


def req(opener, method, path, data=None, timeout=60):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        resp = opener.open(r, timeout=timeout)
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except Exception:
            return e.code, {"detail": raw[:200].decode(errors="ignore")}


def copy_materials_from(opener, orig_id: str, new_id: str) -> None:
    """从原版项目复制素材（世界观字段 + 角色 + 关系 + 组织 + 大纲）。"""
    import subprocess

    def psql(q):
        return subprocess.run(
            ["docker", "exec", "mumuainovel-postgres", "psql", "-U", "mumuai", "-d", "mumuai_novel", "-t", "-A", "-c", q],
            capture_output=True, text=True).stdout.strip()

    # 世界观字段
    row = psql(f"SELECT world_time_period, world_location, world_atmosphere, world_rules, narrative_perspective "
               f"FROM projects WHERE id='{orig_id}'")
    if row:
        fields = row.split("|")
        mapping = ["world_time_period", "world_location", "world_atmosphere", "world_rules", "narrative_perspective"]
        sets = ", ".join(f"{mapping[i]}='{str(fields[i]).replace(chr(39), chr(39) + chr(39))}'" for i in range(min(len(fields), 5)))
        psql(f"UPDATE projects SET {sets} WHERE id='{new_id}'")
    # 角色
    psql(f"INSERT INTO characters (id, project_id, name, age, gender, is_organization, role_type, personality, background, appearance, relationships, status, created_at, updated_at) "
         f"SELECT gen_random_uuid()::text, '{new_id}', name, age, gender, is_organization, role_type, personality, background, appearance, relationships, status, now(), now() "
         f"FROM characters WHERE project_id='{orig_id}'")
    # 角色关系（通过 name 映射）
    psql(f"""INSERT INTO character_relationships (id, project_id, character_from_id, character_to_id, relationship_type_id, relationship_name, intimacy_level, status, description)
             SELECT gen_random_uuid()::text, '{new_id}', nc1.id, nc2.id, r.relationship_type_id, r.relationship_name, r.intimacy_level, r.status, r.description
             FROM character_relationships r
             JOIN characters oc1 ON oc1.id=r.character_from_id AND oc1.project_id='{orig_id}'
             JOIN characters nc1 ON nc1.project_id='{new_id}' AND nc1.name=oc1.name
             JOIN characters oc2 ON oc2.id=r.character_to_id AND oc2.project_id='{orig_id}'
             JOIN characters nc2 ON nc2.project_id='{new_id}' AND nc2.name=oc2.name
             WHERE r.project_id='{orig_id}'""")
    # 大纲（title/content/structure/order_index）
    outlines = psql(f"SELECT id||'||'||replace(title,'|','/')||'||'||replace(coalesce(content,''),'|','/')||'||'||replace(coalesce(structure,''),'|','/')||'||'||order_index "
                    f"FROM outlines WHERE project_id='{orig_id}' ORDER BY order_index")
    for line in outlines.splitlines():
        parts = line.split("||", 4)
        if len(parts) < 5:
            continue
        _, otitle, ocontent, ostr, oidx = parts
        st, o = req(opener, "POST", "/api/outlines", {
            "project_id": new_id, "title": otitle[:200], "content": (ocontent or "概要")[:2000], "order_index": int(oidx),
        })
        if ostr and ostr != "None":
            oid = o.get("id")
            if oid:
                psql(f"UPDATE outlines SET structure={json.dumps(ostr)}::jsonb WHERE id='{oid}'")
    print(f"  已从原版复制素材：角色/关系/大纲")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--theme", default="测试主题")
    ap.add_argument("--genre", default="都市")
    ap.add_argument("--copy-from", default=None, help="原版项目 id，复制完整素材")
    ap.add_argument("--pipeline", type=int, default=0, help=">0 时自动启动流水线写 N 章")
    args = ap.parse_args()

    pw = os.environ.get("ADMIN_PASSWORD", "")
    opener = login(pw)
    st, proj = req(opener, "POST", "/api/projects",
                   {"title": args.title, "theme": args.theme, "genre": args.genre})
    assert st == 200, f"建项目失败: {proj}"
    pid = proj["id"]
    print(f"项目已建: {pid}（description 已自动兜底: {proj.get('description', '')[:20]}...）")

    if args.copy_from:
        copy_materials_from(opener, args.copy_from, pid)
        print("✅ 素材复制完成（世界观/角色/关系/大纲）")

    if args.pipeline > 0:
        cfg = {
            "checkpoint_every_n": 0, "milestone_chapters": args.pipeline,
            "checkpoint_on_volume_end": False, "volume_chapters": args.pipeline + 5,
            "models": {"chapter": {"provider_config_id": "333f8891-d891-4134-b411-91a84cc051b1", "model": "deepseek-v4-flash"}},
            "params": {"chapter": {"target_word_count": 1200, "max_tokens": 12000, "temperature": 0.85}},
        }
        st, pl = req(opener, "POST", "/api/pipelines/start", {"project_id": pid, "config": cfg})
        assert st == 200, f"启动流水线失败: {pl}"
        print(f"流水线已启动: {pl.get('id')}（目标 {args.pipeline} 章）")
        # 轮询到检查点
        plid = pl["id"]
        deadline = time.time() + args.pipeline * 600 + 300
        while time.time() < deadline:
            st, pl = req(opener, "GET", f"/api/pipelines/{plid}")
            if pl.get("status") in ("awaiting_review", "failed", "paused", "stopped"):
                print(f"流水线状态: {pl.get('status')} | 章节: {pl.get('chapter_count')} | 错误: {pl.get('last_error')}")
                break
            time.sleep(10)
        else:
            print("等待超时")

    print(f"\n✅ 测试书就绪: {pid}\n页面: {BASE}/project/{pid}")


if __name__ == "__main__":
    main()
