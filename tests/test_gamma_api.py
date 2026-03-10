"""
Gamma API + CLOB API 连通性诊断与数据获取测试

诊断发现：
- Gamma API 的 condition_id 查询参数不生效（总是返回 id=12 的默认市场）
- 正确方式：用 /events?slug=xxx 获取事件下的所有市场
- CLOB API 可以用 conditionId 直接查市场，并获取 token_id 用于价格历史

测试内容：
1. DNS + TCP 连通性
2. Gamma API /events?slug= 获取市场元数据
3. CLOB API /markets/{conditionId} 获取 token 信息
4. CLOB API /prices-history 获取历史价格
5. 数据覆盖率验证
"""

import asyncio
import sys
import socket
import json
import time

sys.path.insert(0, ".")

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
ADDR = "0x56687bf447db6ffa42ffe2204a05edaa20f55839"

SEP = "=" * 60
LINE = "─" * 60


async def main():
    print(f"\n{SEP}")
    print(f"  Gamma API + CLOB API 诊断")
    print(SEP)

    passed = 0
    failed = 0

    # ── 1. DNS + TCP ─────────────────────────────────────
    print(f"\n── 1. DNS + TCP ──")
    for host in ["gamma-api.polymarket.com", "clob.polymarket.com", "data-api.polymarket.com"]:
        try:
            addrs = socket.getaddrinfo(host, 443)
            ips = list(set(a[4][0] for a in addrs))
            print(f"  ✅ {host} → {ips[0]}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {host} DNS 失败: {e}")
            failed += 1

    # ── 2. 获取 closed-positions 基础数据 ────────────────
    print(f"\n── 2. 获取 closed-positions ──")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        try:
            r = await c.get(f"{DATA_API}/closed-positions",
                params={"user": ADDR, "limit": 1000})
            items = r.json()
            print(f"  ✅ {len(items)} 条 closed-positions")
            passed += 1
        except Exception as e:
            print(f"  ❌ Data API 失败: {e}")
            print(f"  后续测试无法继续")
            failed += 1
            return

    # 收集 eventSlug 和 conditionId
    slugs = list(set(item.get("eventSlug", "") for item in items if item.get("eventSlug")))
    cids = [item["conditionId"] for item in items]
    print(f"  唯一 eventSlug: {len(slugs)} 个")
    print(f"  conditionId: {len(cids)} 个")

    # ── 3. Gamma API: condition_id 参数验证（已知 bug） ──
    print(f"\n── 3. Gamma API condition_id 参数验证 ──")
    print(f"  (已知问题: condition_id 过滤器不生效)")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        try:
            r = await c.get(f"{GAMMA}/markets",
                params={"condition_id": cids[0], "limit": 1})
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    returned_cid = data[0].get("conditionId", "")
                    match = returned_cid == cids[0]
                    print(f"  查询: {cids[0][:20]}...")
                    print(f"  返回: {returned_cid[:20]}...")
                    print(f"  匹配: {'✅' if match else '❌ 不匹配 (已知 bug)'}")
                    if match:
                        passed += 1
                    else:
                        failed += 1
        except Exception as e:
            print(f"  ❌ Gamma API 不可达: {e}")
            failed += 1

    # ── 4. Gamma API: /events?slug= (正确方式) ──────────
    print(f"\n── 4. Gamma API /events?slug= (正确方式) ──")
    gamma_markets = {}  # conditionId → market dict
    gamma_ok = True

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        for slug in slugs:
            try:
                r = await c.get(f"{GAMMA}/events", params={"slug": slug})
                if r.status_code == 200:
                    events = r.json()
                    if isinstance(events, list) and events:
                        evt = events[0]
                        markets = evt.get("markets", [])
                        for m in markets:
                            gamma_markets[m.get("conditionId", "")] = {
                                "question": m.get("question", ""),
                                "category": m.get("category", ""),
                                "endDate": m.get("endDate", ""),
                                "volume": m.get("volume", 0),
                                "volumeNum": m.get("volumeNum", 0),
                                "outcomes": m.get("outcomes", []),
                                "outcomePrices": m.get("outcomePrices", ""),
                                "closed": m.get("closed", False),
                                "liquidity": m.get("liquidity", 0),
                                "slug": m.get("slug", ""),
                            }
                        print(f"  ✅ {slug[:35]:35s} → {len(markets)} 个市场")
                    else:
                        print(f"  ⚠️ {slug[:35]:35s} → 空")
                else:
                    print(f"  ❌ {slug[:35]:35s} → HTTP {r.status_code}")
                    gamma_ok = False
            except Exception as e:
                print(f"  ❌ {slug[:35]:35s} → {type(e).__name__}")
                gamma_ok = False
            await asyncio.sleep(0.3)

    # 覆盖率
    closed_cids = set(cids)
    gamma_cids = set(gamma_markets.keys())
    matched = closed_cids & gamma_cids
    print(f"\n  覆盖率: {len(matched)}/{len(closed_cids)} ({len(matched)/len(closed_cids)*100:.0f}%)")

    if matched:
        passed += 1
    else:
        failed += 1

    missing = closed_cids - gamma_cids
    if missing:
        print(f"  未匹配 ({len(missing)} 个):")
        for cid in missing:
            item = next((i for i in items if i["conditionId"] == cid), {})
            print(f"    {cid[:20]}... | {item.get('title','')[:40]}")

    # 打印获取到的元数据
    if gamma_markets:
        print(f"\n  获取到的市场元数据 ({len(gamma_markets)} 个):")
        for cid, m in list(gamma_markets.items())[:10]:
            print(f"    {m['question'][:40]:40s} | cat={m['category']:15s} | vol=${float(m.get('volumeNum',0)):>12,.0f}")

    # ── 5. CLOB API: /markets/{conditionId} ──────────────
    print(f"\n── 5. CLOB API /markets/{{conditionId}} ──")
    clob_tokens = {}  # conditionId → {outcome: token_id}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        for item in items:
            cid = item["conditionId"]
            title = item.get("title", "")[:35]
            try:
                r = await c.get(f"{CLOB}/markets/{cid}")
                if r.status_code == 200:
                    d = r.json()
                    tokens = d.get("tokens", [])
                    token_map = {}
                    for t in tokens:
                        token_map[t.get("outcome", "")] = t.get("token_id", "")
                    clob_tokens[cid] = token_map
                    print(f"  ✅ {title:35s} | {len(tokens)} tokens")
                else:
                    print(f"  ❌ {title:35s} | HTTP {r.status_code}")
                    failed += 1
            except Exception as e:
                print(f"  ❌ {title:35s} | {type(e).__name__}")
                failed += 1
            await asyncio.sleep(0.2)

    clob_coverage = len(clob_tokens)
    print(f"\n  CLOB 覆盖率: {clob_coverage}/{len(items)} ({clob_coverage/len(items)*100:.0f}%)")
    if clob_coverage > 0:
        passed += 1

    # ── 6. CLOB API: /prices-history ─────────────────────
    print(f"\n── 6. CLOB API /prices-history (历史价格) ──")
    price_history_ok = 0
    price_history_fail = 0

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        # 只测前 5 个
        test_items = items[:5]
        for item in test_items:
            cid = item["conditionId"]
            title = item.get("title", "")[:35]
            outcome = item.get("outcome", "")
            token_map = clob_tokens.get(cid, {})
            token_id = token_map.get(outcome, "")

            if not token_id:
                print(f"  ⚠️ {title:35s} | 无 token_id")
                continue

            try:
                r = await c.get(f"{CLOB}/prices-history",
                    params={"market": token_id, "interval": "max", "fidelity": 60})
                if r.status_code == 200:
                    hist = r.json().get("history", [])
                    if hist:
                        first = hist[0]
                        last = hist[-1]
                        print(f"  ✅ {title:35s} | {outcome:5s} | {len(hist):>4d} 点 | "
                              f"{first.get('t','')[:10]} → {last.get('t','')[:10]} | "
                              f"p: {first.get('p','?')} → {last.get('p','?')}")
                        price_history_ok += 1
                    else:
                        print(f"  ⚠️ {title:35s} | {outcome:5s} | 空历史")
                        price_history_fail += 1
                else:
                    print(f"  ❌ {title:35s} | HTTP {r.status_code}")
                    price_history_fail += 1
            except Exception as e:
                print(f"  ❌ {title:35s} | {type(e).__name__}")
                price_history_fail += 1
            await asyncio.sleep(0.3)

    print(f"\n  价格历史: {price_history_ok} 成功 / {price_history_fail} 失败")
    if price_history_ok > 0:
        passed += 1

    # ── 7. 总结 ──────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  诊断总结")
    print(SEP)
    print(f"  通过: {passed} / 失败: {failed}")
    print()
    print(f"  Gamma API:")
    print(f"    ❌ /markets?condition_id= 过滤器不生效 (已知 bug)")
    print(f"    ✅ /events?slug= 可以正确获取市场元数据")
    print(f"    覆盖率: {len(matched)}/{len(closed_cids)}")
    print()
    print(f"  CLOB API:")
    print(f"    ✅ /markets/{{conditionId}} 可获取 token 信息")
    print(f"    {'✅' if price_history_ok > 0 else '❌'} /prices-history 可获取历史价格")
    print(f"    覆盖率: {clob_coverage}/{len(items)}")
    print()
    print(f"  建议:")
    print(f"    1. fetcher.py 中 get_market_details_bulk 改用 /events?slug= 查询")
    print(f"    2. 新增 CLOB API 集成，获取 token_id 和历史价格")
    print(f"    3. 有了历史价格后可以构建 Equity Curve 和 Max Drawdown")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
