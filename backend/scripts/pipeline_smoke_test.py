#!/usr/bin/env python3
"""流水线冒烟测试：验证核心流程不回归（建书→写章节→检查点→素材完整性）。

每次修改流水线/章节/建书相关代码后，建议运行：
  python3 pipeline_smoke_test.py

覆盖：
1. 建书素材完整性（description/世界观/角色/大纲非空）
2. 章节生成落库且字数达标（>目标70%）
3. 检查点触发（awaiting_review）
4. 清理测试数据
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("MUMU_BASE", "http://127.0.0.1:19000")
OPENCODE_GO = "333f8891-d891-4134-b411-91a84cc051b1"


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


def psql(q):
    return subprocess.run(
        ["docker", "exec", "mumuainovel-postgres", "psql", "-U", "mumuai", "-d", "mumuai_novel", "-t", "-A", "-c", q],
        capture_output=True, text=True).stdout.strip()


def main():
    import http.cookiejar

    pw = os.environ.get("ADMIN_PASSWORD", "")
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req(opener, "POST", "/api/auth/local/login", {"username": "admin", "password": pw})

    title = f"冒烟测试-{int(time.time())}"
    st, proj = req(opener, "POST", "/api/projects", {"title": title, "theme": "冒烟测试主题", "genre": "都市"})
    assert st == 200, f"建项目失败: {proj}"
    pid = proj["id"]
    ok = True

    try:
        # 1) 素材完整性：description 兜底
        d = req(opener, "GET", f"/api/projects/{pid}")[1]
        assert (d.get("description") or "").strip(), "description 为空（兜底失效）"
        print("✅ 1. 项目 description 已兜底非空")

        # 2) 启动流水线（1章）
        cfg = {
            "checkpoint_every_n": 0, "milestone_chapters": 1,
            "checkpoint_on_volume_end": False, "volume_chapters": 3,
            "models": {"chapter": {"provider_config_id": OPENCODE_GO, "model": "deepseek-v4-flash"}},
            "params": {"chapter": {"target_word_count": 800, "max_tokens": 12000, "temperature": 0.85}},
        }
        st, pl = req(opener, "POST", "/api/pipelines/start", {"project_id": pid, "config": cfg})
        assert st == 200, f"启动流水线失败: {pl}"
        plid = pl["id"]

        # 3) 等第1章完成
        deadline = time.time() + 900
        while time.time() < deadline:
            st, pl = req(opener, "GET", f"/api/pipelines/{plid}")
            if pl.get("status") in ("awaiting_review", "failed", "paused", "stopped"):
                break
            time.sleep(10)
        assert pl.get("status") == "awaiting_review", f"流水线未到检查点: {pl.get('status')} {pl.get('last_error')}"
        print(f"✅ 2. 流水线到达检查点（awaiting_review）")

        # 4) 章节落库 + 字数达标
        chs = psql(f"SELECT chapter_number||'|'||status||'|'||length(content) FROM chapters WHERE project_id='{pid}' AND status='completed'")
        assert chs, "没有 completed 章节"
        for line in chs.splitlines():
            num, status, length = line.split("|")
            assert int(length) >= int(800 * 0.7), f"第{num}章字数不足: {length}"
        print("✅ 3. 章节已落库且字数达标")

        # 5) 素材完整（一键开书后：世界观+角色+大纲）
        world = psql(f"SELECT count(*) FROM projects WHERE id='{pid}' AND world_time_period<>'' AND world_location<>'' AND world_rules<>''")
        assert world == "1", "世界观字段缺失"
        chars = int(psql(f"SELECT count(*) FROM characters WHERE project_id='{pid}'"))
        outlines = int(psql(f"SELECT count(*) FROM outlines WHERE project_id='{pid}'"))
        assert chars > 0 and outlines > 0, f"角色/大纲缺失: chars={chars} outlines={outlines}"
        print(f"✅ 4. 素材完整（世界观✓ 角色{chars}✓ 大纲{outlines}✓）")

        print("\n🎉 冒烟测试全部通过")
    except AssertionError as e:
        ok = False
        print(f"\n❌ 冒烟测试失败: {e}")
    finally:
        req(opener, "DELETE", f"/api/projects/{pid}")
        print(f"已清理测试项目 {pid}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
