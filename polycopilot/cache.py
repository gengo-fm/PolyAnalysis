"""
CacheManager — 本地数据缓存管理模块

核心能力：
- 按钱包地址存储 Parquet 数据和 JSON 元数据
- 支持增量更新和缓存验证
- 提供缓存统计和管理功能
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


@dataclass
class CacheMetadata:
    """缓存元数据"""
    address: str
    first_fetch: str  # ISO 8601
    last_fetch: str
    activity_count: int
    activity_latest_timestamp: str  # ISO 8601
    closed_count: int
    fetch_history: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "CacheMetadata":
        return cls(**data)


class CacheManager:
    """本地数据缓存管理器"""
    
    def __init__(self, cache_dir: Path | str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_address_dir(self, address: str) -> Path:
        """获取地址的缓存目录"""
        return self.cache_dir / address
    
    def _get_metadata_path(self, address: str) -> Path:
        """获取元数据文件路径"""
        return self._get_address_dir(address) / "metadata.json"
    
    # ── 元数据操作 ──────────────────────────────────────────
    
    def load_metadata(self, address: str) -> CacheMetadata | None:
        """加载元数据，不存在返回 None"""
        meta_path = self._get_metadata_path(address)
        if not meta_path.exists():
            return None
        
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return CacheMetadata.from_dict(data)
        except Exception as e:
            logger.warning(f"元数据加载失败 {address}: {e}")
            return None
    
    def save_metadata(self, address: str, meta: CacheMetadata):
        """保存元数据"""
        addr_dir = self._get_address_dir(address)
        addr_dir.mkdir(parents=True, exist_ok=True)
        
        meta_path = self._get_metadata_path(address)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.to_dict(), f, indent=2, ensure_ascii=False)
        
        logger.debug(f"元数据已保存: {address}")
    
    # ── 数据操作 ──────────────────────────────────────────
    
    def load_data(self, address: str) -> dict[str, pd.DataFrame]:
        """
        加载所有 Parquet 数据
        
        Returns:
            {
                "activity": DataFrame,
                "closed_positions": DataFrame,
                "positions": DataFrame
            }
        """
        addr_dir = self._get_address_dir(address)
        
        data = {}
        for name in ["activity", "closed_positions", "positions"]:
            path = addr_dir / f"{name}.parquet"
            if path.exists():
                try:
                    data[name] = pd.read_parquet(path)
                    logger.debug(f"加载 {name}: {len(data[name])} 条")
                except Exception as e:
                    logger.warning(f"加载 {name} 失败: {e}")
                    data[name] = pd.DataFrame()
            else:
                data[name] = pd.DataFrame()
        
        return data
    
    def save_data(self, address: str, data: dict[str, pd.DataFrame]):
        """保存所有 Parquet 数据"""
        addr_dir = self._get_address_dir(address)
        addr_dir.mkdir(parents=True, exist_ok=True)
        
        for name, df in data.items():
            if name in ["activity", "closed_positions", "positions"]:
                path = addr_dir / f"{name}.parquet"
                df.to_parquet(path, index=False)
                logger.debug(f"保存 {name}: {len(df)} 条")
    
    # ── 缓存管理 ──────────────────────────────────────────
    
    def clear_cache(self, address: str):
        """删除指定地址的缓存"""
        addr_dir = self._get_address_dir(address)
        if addr_dir.exists():
            import shutil
            shutil.rmtree(addr_dir)
            logger.info(f"缓存已清除: {address}")
    
    def clear_all_caches(self):
        """清除所有缓存"""
        if self.cache_dir.exists():
            import shutil
            for addr_dir in self.cache_dir.iterdir():
                if addr_dir.is_dir():
                    shutil.rmtree(addr_dir)
            logger.info("所有缓存已清除")
    
    def list_cached(self) -> list[str]:
        """列出所有已缓存的地址"""
        if not self.cache_dir.exists():
            return []
        
        addresses = []
        for addr_dir in self.cache_dir.iterdir():
            if addr_dir.is_dir() and (addr_dir / "metadata.json").exists():
                addresses.append(addr_dir.name)
        
        return sorted(addresses)
    
    def get_stats(self, address: str) -> dict[str, Any]:
        """获取缓存统计信息"""
        meta = self.load_metadata(address)
        if meta is None:
            return {"exists": False}
        
        addr_dir = self._get_address_dir(address)
        
        # 计算缓存大小
        total_size = 0
        for path in addr_dir.rglob("*"):
            if path.is_file():
                total_size += path.stat().st_size
        
        # 计算缓存年龄
        last_fetch_dt = datetime.fromisoformat(meta.last_fetch)
        age_hours = (datetime.now(timezone.utc) - last_fetch_dt).total_seconds() / 3600
        
        return {
            "exists": True,
            "address": address,
            "first_fetch": meta.first_fetch,
            "last_fetch": meta.last_fetch,
            "age_hours": round(age_hours, 1),
            "activity_count": meta.activity_count,
            "closed_count": meta.closed_count,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "fetch_count": len(meta.fetch_history),
        }
    
    def validate_cache(self, address: str) -> tuple[bool, str]:
        """
        验证缓存完整性
        
        Returns:
            (is_valid, error_message)
        """
        meta = self.load_metadata(address)
        if meta is None:
            return False, "元数据不存在"
        
        addr_dir = self._get_address_dir(address)
        
        # 检查必需文件
        required_files = ["activity.parquet", "closed_positions.parquet", "positions.parquet"]
        for filename in required_files:
            path = addr_dir / filename
            if not path.exists():
                return False, f"缺少文件: {filename}"
        
        # 尝试读取 Parquet 文件
        try:
            data = self.load_data(address)
            
            # 验证记录数
            if len(data["activity"]) != meta.activity_count:
                return False, f"activity 记录数不匹配: {len(data['activity'])} != {meta.activity_count}"
            
            if len(data["closed_positions"]) != meta.closed_count:
                return False, f"closed_positions 记录数不匹配: {len(data['closed_positions'])} != {meta.closed_count}"
            
        except Exception as e:
            return False, f"数据读取失败: {e}"
        
        return True, "缓存有效"
