#!/usr/bin/env python3
"""
PolyAnalysis CLI — 钱包分析命令行工具

用法:
    python analyze.py <address>              # 分析钱包（自动增量）
    python analyze.py <address> --force      # 强制全量刷新
    python analyze.py <address> --json       # JSON 输出
    python analyze.py cache list             # 列出缓存
    python analyze.py cache show <address>   # 查看缓存详情
    python analyze.py cache clear <address>  # 清除缓存
    python analyze.py cache clear --all      # 清除所有缓存
    python analyze.py cache stats            # 缓存统计
"""

import argparse
import asyncio
import json
import sys
import time

from loguru import logger

from polycopilot.cache import CacheManager
from polycopilot.fetcher import PolymarketFetcher
from polycopilot.processor import TradeProcessor
from polycopilot.analyzer import WalletAnalyzer
from polycopilot.discovery import WalletDiscoveryModule


# ── 日志配置 ──────────────────────────────────────────────

def setup_logging(verbose: bool = False, quiet: bool = False):
    """配置日志级别"""
    logger.remove()
    if quiet:
        logger.add(sys.stderr, level="ERROR")
    elif verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")


# ── 分析命令 ──────────────────────────────────────────────

async def run_analysis(
    address: str,
    force: bool = False,
    json_output: bool = False,
    # TradeFox 跟单参数
    copy_delay: float = 0.3,
    min_liquidity: float = 10000,
    max_slippage: float = 1.0,
):
    """执行钱包分析"""
    cache_mgr = CacheManager()
    
    if force:
        logger.info("强制模式: 清除缓存并全量拉取")
        cache_mgr.clear_cache(address)
    
    # 获取数据（自动判断全量/增量）
    async with PolymarketFetcher() as fetcher:
        data = await fetcher.fetch_incremental(address, cache_mgr)
    
    fetch_type = data.get("fetch_type", "unknown")
    stats = data.get("stats", {})
    
    logger.info(
        f"数据获取完成 | 类型: {fetch_type} | "
        f"新增 activity: {stats.get('activity_new', '?')} | "
        f"缓存 activity: {stats.get('activity_cached', '?')} | "
        f"耗时: {stats.get('duration_seconds', '?')}s"
    )
    
    # 处理数据
    processor = TradeProcessor(
        activity_df=data["activity"],
        closed_positions_df=data["closed_positions"],
    )
    processor.build_reports()
    
    if not processor.reports:
        logger.error("无法生成报告: 没有有效的交易数据")
        sys.exit(1)
    
    # 分析 - 传入 TradeFox 参数
    analyzer = WalletAnalyzer(
        processor.reports,
        address=address,
        copy_delay_seconds=copy_delay,
        min_market_liquidity=min_liquidity,
        max_slippage_pct=max_slippage,
    )
    
    # 生成完整报告
    report = analyzer.generate_report()
    
    # 保存报告
    report_path = analyzer.save_report(output_dir="data")
    
    if json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        # 打印摘要
        print_summary(address, report, data)
    
    return analyzer


def print_summary(address: str, report: dict, data: dict):
    """打印分析摘要"""
    stats = data.get("stats", {})
    fetch_type = data.get("fetch_type", "unknown")
    
    print(f"\n{'='*60}")
    print(f"  钱包分析完成: {address}")
    print(f"{'='*60}")
    print(f"  获取方式: {'全量' if fetch_type == 'full' else '增量'}")
    print(f"  耗时: {stats.get('duration_seconds', '?')}s")
    print(f"  新增 activity: {stats.get('activity_new', '?')}")
    print(f"  缓存 activity: {stats.get('activity_cached', '?')}")
    
    # 从报告中提取关键指标
    summary_outcome = report.get('summary', {}).get('outcome_level', {})
    score = report.get('copy_trading_score', {})
    
    if summary_outcome:
        print(f"\n  --- 核心指标 ---")
        print(f"  总 PnL: ${summary_outcome.get('total_pnl', 0):,.2f}")
        print(f"  ROI: {summary_outcome.get('roi_pct', 0):+.1f}%")
        print(f"  胜率: {summary_outcome.get('win_rate_pct', 0):.1f}%")
    
    if score:
        print(f"\n  --- 跟单评分 ---")
        print(f"  评分: {score.get('total', 0):.1f}/100")
        print(f"  等级: {score.get('grade', '?')}")
    
    print(f"\n  报告已保存: data/{address[:10]}_report.json")
    print(f"{'='*60}\n")


# ── 缓存管理命令 ──────────────────────────────────────────

def cmd_cache_list():
    """列出所有缓存"""
    cache_mgr = CacheManager()
    addresses = cache_mgr.list_cached()
    
    if not addresses:
        print("无缓存数据")
        return
    
    print(f"\n已缓存 {len(addresses)} 个地址:\n")
    for addr in addresses:
        stats = cache_mgr.get_stats(addr)
        print(
            f"  {addr} | "
            f"activity: {stats.get('activity_count', '?')} 条 | "
            f"closed: {stats.get('closed_count', '?')} 条 | "
            f"大小: {stats.get('total_size_mb', '?')} MB | "
            f"更新: {stats.get('age_hours', '?')}h 前"
        )
    print()


def cmd_cache_show(address: str):
    """显示缓存详情"""
    cache_mgr = CacheManager()
    stats = cache_mgr.get_stats(address)
    
    if not stats.get("exists"):
        print(f"地址 {address} 无缓存")
        return
    
    print(f"\n缓存详情: {address}\n")
    for key, value in stats.items():
        if key != "exists":
            print(f"  {key}: {value}")
    
    # 验证
    is_valid, msg = cache_mgr.validate_cache(address)
    print(f"\n  验证: {'✅ ' + msg if is_valid else '❌ ' + msg}")
    print()


def cmd_cache_clear(address: str | None = None, clear_all: bool = False):
    """清除缓存"""
    cache_mgr = CacheManager()
    
    if clear_all:
        cache_mgr.clear_all_caches()
        print("所有缓存已清除")
    elif address:
        cache_mgr.clear_cache(address)
        print(f"缓存已清除: {address}")
    else:
        print("请指定地址或使用 --all")


def cmd_cache_stats():
    """缓存统计"""
    cache_mgr = CacheManager()
    addresses = cache_mgr.list_cached()
    
    if not addresses:
        print("无缓存数据")
        return
    
    total_size = 0
    total_activity = 0
    total_closed = 0
    
    for addr in addresses:
        stats = cache_mgr.get_stats(addr)
        total_size += stats.get("total_size_mb", 0)
        total_activity += stats.get("activity_count", 0)
        total_closed += stats.get("closed_count", 0)
    
    print(f"\n缓存统计:")
    print(f"  地址数: {len(addresses)}")
    print(f"  总 activity: {total_activity} 条")
    print(f"  总 closed: {total_closed} 条")
    print(f"  总大小: {total_size:.2f} MB")
    print()


# ── 钱包发现 ──────────────────────────────────────────────

async def run_discovery(
    sources: list[str],
    top_n: int,
    min_profit: float,
    min_volume: float,
    output_json: bool,
    output_file: str = None,
):
    """执行钱包发现"""
    cache_mgr = CacheManager()
    
    discovery = WalletDiscoveryModule(
        cache_manager=cache_mgr,
        copy_delay_seconds=0.3,
        min_market_liquidity=10000,
        max_slippage_pct=1.0,
    )
    
    logger.info(f"开始钱包发现: sources={sources}, top_n={top_n}")
    
    wallets = await discovery.discover_wallets(
        sources=sources,
        max_wallets_to_analyze=top_n,
        min_profit_threshold=min_profit,
        min_volume_threshold=min_volume,
        min_active_days=30,
    )
    
    # 输出结果
    if output_json:
        output = json.dumps(wallets, indent=2, ensure_ascii=False, default=str)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(output)
            logger.info(f"结果已保存到 {output_file}")
        else:
            print(output)
    else:
        # 终端表格输出
        print(f"\n{'='*80}")
        print(f"  发现 {len(wallets)} 个聪明钱钱包")
        print(f"{'='*80}\n")
        
        for i, wallet in enumerate(wallets, 1):
            addr = wallet.get("address", "unknown")
            score_data = wallet.get("copy_trading_score", {})
            score = score_data.get("total", 0)
            grade = score_data.get("grade", "?")
            
            summary = wallet.get("summary", {}).get("outcome_level", {})
            pnl = summary.get("total_pnl", 0)
            roi = summary.get("roi_pct", 0)
            wr = summary.get("win_rate_pct", 0)
            
            print(f"  {i}. {addr[:10]}... | 评分: {score:.1f} ({grade}) | PnL: ${pnl:,.0f} | ROI: {roi:+.1f}% | 胜率: {wr:.1f}%")
        
        print(f"\n{'='*80}\n")
        
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(wallets, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"完整报告已保存到 {output_file}")


# ── 主入口 ────────────────────────────────────────────────

def main():
    # 如果第一个参数是 "cache"，走缓存管理
    if len(sys.argv) > 1 and sys.argv[1] == "cache":
        cache_parser = argparse.ArgumentParser(prog="analyze.py cache")
        cache_sub = cache_parser.add_subparsers(dest="cache_command")
        
        cache_sub.add_parser("list", help="列出缓存")
        cache_sub.add_parser("stats", help="缓存统计")
        
        show_p = cache_sub.add_parser("show", help="查看缓存详情")
        show_p.add_argument("address", help="钱包地址")
        
        clear_p = cache_sub.add_parser("clear", help="清除缓存")
        clear_p.add_argument("address", nargs="?", help="钱包地址")
        clear_p.add_argument("--all", action="store_true", help="清除所有")
        
        args = cache_parser.parse_args(sys.argv[2:])
        
        if args.cache_command == "list":
            cmd_cache_list()
        elif args.cache_command == "show":
            cmd_cache_show(args.address)
        elif args.cache_command == "clear":
            cmd_cache_clear(
                address=getattr(args, "address", None),
                clear_all=getattr(args, "all", False),
            )
        elif args.cache_command == "stats":
            cmd_cache_stats()
        else:
            cache_parser.print_help()
        return
    
    # 如果第一个参数是 "discover"，走钱包发现
    if len(sys.argv) > 1 and sys.argv[1] == "discover":
        discover_parser = argparse.ArgumentParser(prog="analyze.py discover")
        discover_parser.add_argument("--sources", type=str, default="polymarket",
                                    help="数据源 (逗号分隔): polymarket, tradefox, hashdive, on_chain")
        discover_parser.add_argument("--top-n", type=int, default=10,
                                    help="返回前 N 个钱包，默认 10")
        discover_parser.add_argument("--min-profit", type=float, default=100000.0,
                                    help="最小盈利门槛 (USD)，默认 100000")
        discover_parser.add_argument("--min-volume", type=float, default=500000.0,
                                    help="最小交易量门槛 (USD)，默认 500000")
        discover_parser.add_argument("--output-json", action="store_true",
                                    help="输出 JSON 格式")
        discover_parser.add_argument("--output-file", type=str,
                                    help="保存到文件")
        discover_parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
        discover_parser.add_argument("--quiet", "-q", action="store_true", help="静默模式")
        
        args = discover_parser.parse_args(sys.argv[2:])
        
        setup_logging(verbose=args.verbose, quiet=args.quiet)
        asyncio.run(run_discovery(
            sources=args.sources.split(","),
            top_n=args.top_n,
            min_profit=args.min_profit,
            min_volume=args.min_volume,
            output_json=args.output_json,
            output_file=args.output_file,
        ))
        return
    
    # 否则走分析命令
    parser = argparse.ArgumentParser(
        description="PolyAnalysis — Polymarket 钱包分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("address", help="钱包地址")
    parser.add_argument("--force", "-f", action="store_true", help="强制全量刷新")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    parser.add_argument("--quiet", "-q", action="store_true", help="静默模式")
    # TradeFox 参数
    parser.add_argument("--copy-delay", type=float, default=0.3, help="跟单延迟(秒)，默认 0.3 (TradeFox)")
    parser.add_argument("--min-liquidity", type=float, default=10000, help="最小市场流动性，默认 10000")
    parser.add_argument("--max-slippage", type=float, default=1.0, help="最大滑点容忍(%)，默认 1.0")
    
    args = parser.parse_args()
    
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    asyncio.run(run_analysis(
        address=args.address,
        force=args.force,
        json_output=args.json,
        copy_delay=args.copy_delay,
        min_liquidity=args.min_liquidity,
        max_slippage=args.max_slippage,
    ))


if __name__ == "__main__":
    main()
