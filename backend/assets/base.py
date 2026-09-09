"""资源存储抽象基类。

定义 AssetStore 的统一接口，所有存储后端均需实现 put/get/delete 三个方法。
"""

from abc import ABC, abstractmethod

from app.core.models import Asset


class AssetStore(ABC):
    """资源存储的抽象基类。

    定义 Asset 的持久化操作接口。实现类为 PgAssetStore（数据库）或 MinioAssetStore（对象存储）。
    """

    @abstractmethod
    def put(self, asset: Asset) -> None:
        """存储或更新一个 Asset。

        Args:
            asset: 待存储的 Asset 对象。
        """
        ...

    @abstractmethod
    def get(self, asset_id: str) -> Asset | None:
        """按 ID 获取一个 Asset。

        Args:
            asset_id: Asset 的唯一标识。

        Returns:
            匹配的 Asset 对象，不存在时返回 None。
        """
        ...

    @abstractmethod
    def delete(self, asset_id: str) -> None:
        """删除指定 ID 的 Asset。

        Args:
            asset_id: 待删除的 Asset 唯一标识。
        """
        ...
