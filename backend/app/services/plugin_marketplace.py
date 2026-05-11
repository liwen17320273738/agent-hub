"""
Plugin Marketplace — Plugin discovery, registration, and community ecosystem.

Enables external developers to create and share plugins for Agent Hub.
Supports npm-style publishing with built-in moderation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PluginStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"      # Awaiting review
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class PluginCategory(str, Enum):
    TOOL = "tool"              # Tool plugins (e.g., database connectors)
    AGENT = "agent"            # Agent plugins (e.g., new roles)
    WORKFLOW = "workflow"      # Workflow plugins
    INTEGRATION = "integration" # External integrations
    THEME = "theme"            # UI themes
    UTILITY = "utility"        # Utility plugins


@dataclass
class Plugin:
    """A plugin in the marketplace"""
    id: str
    name: str
    version: str
    author: str
    description: str
    category: PluginCategory
    status: PluginStatus = PluginStatus.PENDING
    tags: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    downloads: int = 0
    rating: float = 0.0
    reviews: int = 0
    created_at: str = ""
    updated_at: str = ""
    repository_url: Optional[str] = None
    documentation_url: Optional[str] = None
    license: str = "MIT"
    compatibility: Dict[str, str] = field(default_factory=dict)


@dataclass
class PluginReview:
    """User review for a plugin"""
    id: str
    plugin_id: str
    user_id: str
    rating: float  # 1-5
    title: str
    content: str
    created_at: str
    helpful_count: int = 0


@dataclass
class PluginInstall:
    """Plugin installation record"""
    id: str
    plugin_id: str
    workspace_id: str
    version: str
    installed_at: str
    enabled: bool = True


class PluginMarketplace:
    """
    Plugin marketplace for Agent Hub.
    
    Features:
    - Plugin registration and discovery
    - Semantic versioning support
    - Community reviews and ratings
    - npm-style publishing workflow
    - Built-in moderation queue
    """
    
    def __init__(self):
        self._plugins: Dict[str, Plugin] = {}
        self._installations: Dict[str, List[PluginInstall]] = {}
        self._reviews: Dict[str, List[PluginReview]] = {}
        self._moderation_queue: List[str] = []
    
    # ─────────────────────────────────────────────────────────────
    # Plugin Registration
    # ─────────────────────────────────────────────────────────────
    
    def register_plugin(
        self,
        name: str,
        version: str,
        author: str,
        description: str,
        category: PluginCategory,
        tags: Optional[List[str]] = None,
        dependencies: Optional[Dict[str, str]] = None,
        repository_url: Optional[str] = None,
        license: str = "MIT",
    ) -> Plugin:
        """
        Register a new plugin in the marketplace.
        
        Plugins enter moderation queue for review before being published.
        """
        import uuid
        
        plugin_id = f"plugin_{uuid.uuid4().hex[:12]}"
        
        plugin = Plugin(
            id=plugin_id,
            name=name,
            version=version,
            author=author,
            description=description,
            category=category,
            status=PluginStatus.PENDING,
            tags=tags or [],
            dependencies=dependencies or {},
            repository_url=repository_url,
            license=license,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        
        self._plugins[plugin_id] = plugin
        self._moderation_queue.append(plugin_id)
        
        logger.info(f"Plugin '{name}' v{version} registered (pending review)")
        return plugin
    
    def approve_plugin(self, plugin_id: str, reviewer: str) -> Optional[Plugin]:
        """Approve a plugin from the moderation queue"""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        
        plugin.status = PluginStatus.APPROVED
        plugin.updated_at = datetime.utcnow().isoformat()
        
        if plugin_id in self._moderation_queue:
            self._moderation_queue.remove(plugin_id)
        
        logger.info(f"Plugin '{plugin.name}' approved by {reviewer}")
        return plugin
    
    def reject_plugin(self, plugin_id: str, reason: str) -> Optional[Plugin]:
        """Reject a plugin from the moderation queue"""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        
        plugin.status = PluginStatus.REJECTED
        plugin.updated_at = datetime.utcnow().isoformat()
        
        if plugin_id in self._moderation_queue:
            self._moderation_queue.remove(plugin_id)
        
        logger.info(f"Plugin '{plugin.name}' rejected: {reason}")
        return plugin
    
    # ─────────────────────────────────────────────────────────────
    # Plugin Discovery
    # ─────────────────────────────────────────────────────────────
    
    def search_plugins(
        self,
        query: Optional[str] = None,
        category: Optional[PluginCategory] = None,
        tags: Optional[List[str]] = None,
        sort_by: str = "downloads",
        limit: int = 20,
    ) -> List[Plugin]:
        """Search and filter plugins"""
        results = [
            p for p in self._plugins.values()
            if p.status == PluginStatus.APPROVED
        ]
        
        if query:
            query_lower = query.lower()
            results = [
                p for p in results
                if query_lower in p.name.lower()
                or query_lower in p.description.lower()
            ]
        
        if category:
            results = [p for p in results if p.category == category]
        
        if tags:
            results = [
                p for p in results
                if any(t in p.tags for t in tags)
            ]
        
        # Sort
        if sort_by == "downloads":
            results.sort(key=lambda p: p.downloads, reverse=True)
        elif sort_by == "rating":
            results.sort(key=lambda p: p.rating, reverse=True)
        elif sort_by == "newest":
            results.sort(key=lambda p: p.created_at, reverse=True)
        elif sort_by == "updated":
            results.sort(key=lambda p: p.updated_at, reverse=True)
        
        return results[:limit]
    
    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Get plugin details"""
        return self._plugins.get(plugin_id)
    
    def get_featured_plugins(self, limit: int = 6) -> List[Plugin]:
        """Get featured plugins (highest rated + most downloaded)"""
        approved = [p for p in self._plugins.values() if p.status == PluginStatus.APPROVED]
        
        # Score: 0.5 * rating_normalized + 0.3 * downloads_normalized + 0.2 * reviews_normalized
        max_downloads = max((p.downloads for p in approved), default=1)
        max_reviews = max((p.reviews for p in approved), default=1)
        
        scored = []
        for p in approved:
            score = (
                0.5 * (p.rating / 5.0) +
                0.3 * (p.downloads / max_downloads) +
                0.2 * (p.reviews / max_reviews)
            )
            scored.append((score, p))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:limit]]
    
    # ─────────────────────────────────────────────────────────────
    # Plugin Installation
    # ─────────────────────────────────────────────────────────────
    
    def install_plugin(
        self,
        plugin_id: str,
        workspace_id: str,
        version: Optional[str] = None,
    ) -> Optional[PluginInstall]:
        """Install a plugin for a workspace"""
        import uuid
        
        plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.APPROVED:
            logger.warning(f"Cannot install plugin {plugin_id}: not found or not approved")
            return None
        
        install_version = version or plugin.version
        
        install = PluginInstall(
            id=f"install_{uuid.uuid4().hex[:12]}",
            plugin_id=plugin_id,
            workspace_id=workspace_id,
            version=install_version,
            installed_at=datetime.utcnow().isoformat(),
            enabled=True,
        )
        
        if workspace_id not in self._installations:
            self._installations[workspace_id] = []
        
        self._installations[workspace_id].append(install)
        
        # Increment download count
        plugin.downloads += 1
        
        logger.info(f"Plugin '{plugin.name}' v{install_version} installed in workspace {workspace_id}")
        return install
    
    def uninstall_plugin(self, workspace_id: str, plugin_id: str) -> bool:
        """Uninstall a plugin from a workspace"""
        installations = self._installations.get(workspace_id, [])
        for inst in installations:
            if inst.plugin_id == plugin_id:
                installations.remove(inst)
                logger.info(f"Plugin {plugin_id} uninstalled from workspace {workspace_id}")
                return True
        
        return False
    
    def get_workspace_plugins(self, workspace_id: str) -> List[Plugin]:
        """Get installed plugins for a workspace"""
        installations = self._installations.get(workspace_id, [])
        plugins = []
        for inst in installations:
            plugin = self._plugins.get(inst.plugin_id)
            if plugin:
                plugins.append(plugin)
        return plugins
    
    # ─────────────────────────────────────────────────────────────
    # Reviews & Ratings
    # ─────────────────────────────────────────────────────────────
    
    def add_review(
        self,
        plugin_id: str,
        user_id: str,
        rating: float,
        title: str,
        content: str,
    ) -> Optional[PluginReview]:
        """Add a review for a plugin"""
        import uuid
        
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
        
        if rating < 1 or rating > 5:
            raise ValueError("Rating must be between 1 and 5")
        
        review = PluginReview(
            id=f"review_{uuid.uuid4().hex[:12]}",
            plugin_id=plugin_id,
            user_id=user_id,
            rating=rating,
            title=title,
            content=content,
            created_at=datetime.utcnow().isoformat(),
        )
        
        if plugin_id not in self._reviews:
            self._reviews[plugin_id] = []
        
        self._reviews[plugin_id].append(review)
        
        # Update plugin rating
        all_reviews = self._reviews[plugin_id]
        plugin.rating = round(sum(r.rating for r in all_reviews) / len(all_reviews), 1)
        plugin.reviews = len(all_reviews)
        
        logger.info(f"Review added for plugin '{plugin.name}': {rating}/5")
        return review
    
    def get_reviews(self, plugin_id: str, limit: int = 20) -> List[PluginReview]:
        """Get reviews for a plugin"""
        reviews = self._reviews.get(plugin_id, [])
        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return reviews[:limit]
    
    # ─────────────────────────────────────────────────────────────
    # Marketplace Stats
    # ─────────────────────────────────────────────────────────────
    
    def get_marketplace_stats(self) -> Dict[str, Any]:
        """Get marketplace statistics"""
        all_plugins = list(self._plugins.values())
        approved = [p for p in all_plugins if p.status == PluginStatus.APPROVED]
        pending = [p for p in all_plugins if p.status == PluginStatus.PENDING]
        
        total_downloads = sum(p.downloads for p in approved)
        total_reviews = sum(len(self._reviews.get(p.id, [])) for p in approved)
        
        return {
            "total_plugins": len(all_plugins),
            "published_plugins": len(approved),
            "pending_review": len(pending),
            "total_downloads": total_downloads,
            "total_reviews": total_reviews,
            "by_category": {
                cat.value: sum(1 for p in approved if p.category == cat)
                for cat in PluginCategory
            },
            "top_downloaded": [
                {"name": p.name, "downloads": p.downloads, "rating": p.rating}
                for p in sorted(approved, key=lambda p: p.downloads, reverse=True)[:5]
            ],
            "moderation_queue": len(self._moderation_queue),
        }


# Singleton
_marketplace: Optional[PluginMarketplace] = None


def get_marketplace() -> PluginMarketplace:
    """Get or create the plugin marketplace singleton"""
    global _marketplace
    if _marketplace is None:
        _marketplace = PluginMarketplace()
    return _marketplace
