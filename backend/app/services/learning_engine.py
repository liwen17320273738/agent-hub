"""
Self-Learning Engine — SONA-like pattern extraction and behavior optimization.

This module implements self-learning capabilities inspired by ruflo's SONA
neural patterns, enabling agents to learn from past successes and failures.

Key Capabilities:
1. Pattern Extraction: identify successful approaches from completed tasks
2. Failure Recovery: record what fixed a failed task for future reference  
3. Behavior Optimization: track which agent behaviors lead to best outcomes
4. Knowledge Transfer: share patterns across similar roles and stages
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Set

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class LearningEngine:
    """
    Self-learning engine that extracts patterns and optimizes agent behavior.
    
    Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │                   Learning Engine                        │
    ├─────────────────────────────────────────────────────────┤
    │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  │
    │  │ Pattern     │  │ Failure      │  │ Behavior     │  │
    │  │ Extractor   │  │ Recovery     │  │ Optimizer    │  │
    │  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘  │
    │         │                │                  │           │
    │         └────────────────┼──────────────────┘           │
    │                          ▼                              │
    │               ┌──────────────────┐                     │
    │               │  Knowledge Base  │                     │
    │               │  (Memory + Vector)│                    │
    │               └──────────────────┘                     │
    └─────────────────────────────────────────────────────────┘
    """
    
    def __init__(self):
        self._pattern_cache: Dict[str, List[Dict]] = {}
        self._confidence_threshold = 0.3
        self._max_patterns_per_query = 10
    
    async def learn_from_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        role: str,
        stage_id: str,
        content: str,
        success: bool,
        error: Optional[str] = None,
        fix_description: Optional[str] = None,
        quality_score: float = 0.0,
        tokens_used: int = 0,
        duration_seconds: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Learn from a completed task execution.
        
        Args:
            db: Database session
            task_id: Task identifier
            role: Agent role
            stage_id: Pipeline stage ID
            content: Output content
            success: Whether the task succeeded
            error: Error message if failed
            fix_description: How the error was fixed (if applicable)
            quality_score: Output quality score (0-1)
            tokens_used: Tokens consumed
            duration_seconds: Execution duration
            
        Returns:
            Dict with extracted patterns and optimizations
        """
        patterns = []
        
        if success and quality_score >= 0.7:
            # Extract success patterns
            patterns = await self._extract_success_patterns(
                db, task_id, role, stage_id, content, quality_score, tokens_used, duration_seconds
            )
        
        if not success:
            # Record failure for future recovery
            await self._record_failure(
                db, task_id, role, stage_id, error or "unknown", fix_description
            )
            
            # If we have a fix, record the recovery pattern
            if fix_description and success:
                await self._record_recovery_pattern(
                    db, task_id, role, stage_id, error or "unknown", fix_description
                )
        
        # Update behavior profile
        behavior_changes = await self._optimize_behavior(
            db, role, stage_id, success, quality_score, tokens_used, duration_seconds
        )
        
        return {
            "patterns_extracted": len(patterns),
            "patterns": patterns,
            "behavior_updates": behavior_changes,
            "task_success": success,
        }
    
    async def _extract_success_patterns(
        self,
        db: AsyncSession,
        task_id: str,
        role: str,
        stage_id: str,
        content: str,
        quality_score: float,
        tokens_used: int,
        duration_seconds: float,
    ) -> List[Dict[str, Any]]:
        """Extract patterns from successful task execution"""
        patterns = []
        
        # Pattern 1: Quality threshold pattern
        if quality_score >= 0.9:
            patterns.append({
                "type": "quality_threshold",
                "role": role,
                "stage": stage_id,
                "description": f"High-quality output achieved with score {quality_score}",
                "confidence": 0.8 + (quality_score - 0.9) * 2,  # 0.8-1.0
                "metrics": {
                    "quality_score": quality_score,
                    "tokens_used": tokens_used,
                    "duration_seconds": duration_seconds,
                },
            })
        
        # Pattern 2: Efficiency pattern (low token usage with good quality)
        if tokens_used > 0 and quality_score / (tokens_used / 1000) > 0.5:
            patterns.append({
                "type": "efficiency",
                "role": role,
                "stage": stage_id,
                "description": f"Efficient output: quality={quality_score}, tokens={tokens_used}",
                "confidence": min(0.9, quality_score * 0.8 + 0.2),
                "metrics": {
                    "tokens_per_quality_point": tokens_used / quality_score if quality_score > 0 else 0,
                },
            })
        
        # Pattern 3: Content structure pattern
        content_patterns = self._analyze_content_structure(content)
        for cp in content_patterns:
            patterns.append({
                "type": "content_structure",
                "role": role,
                "stage": stage_id,
                "description": cp["description"],
                "confidence": cp["confidence"],
                "metadata": cp.get("metadata", {}),
            })
        
        # Store patterns to DB
        for p in patterns:
            try:
                await self._store_pattern(db, {
                    "role": role,
                    "stage_id": stage_id,
                    "task_id": task_id,
                    "pattern_type": p["type"],
                    "description": p["description"],
                    "confidence": p["confidence"],
                    "metadata": json.dumps(p.get("metrics", p.get("metadata", {}))),
                })
            except Exception as e:
                logger.warning(f"Failed to store pattern: {e}")
        
        return patterns
    
    def _analyze_content_structure(self, content: str) -> List[Dict[str, Any]]:
        """Analyze content structure for patterns"""
        patterns = []
        
        if not content:
            return patterns
        
        # Check for well-structured sections
        section_count = content.count("## ")
        if section_count >= 5:
            patterns.append({
                "description": f"Well-structured output with {section_count} sections",
                "confidence": min(0.9, section_count * 0.1),
                "metadata": {"section_count": section_count},
            })
        
        # Check for code blocks
        code_blocks = content.count("```")
        if code_blocks >= 6:  # At least 3 complete code blocks
            patterns.append({
                "description": f"Rich code examples: {code_blocks // 2} blocks",
                "confidence": min(0.85, code_blocks * 0.05),
                "metadata": {"code_blocks": code_blocks // 2},
            })
        
        # Check for tables
        table_count = content.count("| ---")
        if table_count >= 2:
            patterns.append({
                "description": f"Structured tables: {table_count} tables",
                "confidence": min(0.8, table_count * 0.15),
                "metadata": {"table_count": table_count},
            })
        
        # Check for actionable items
        checkbox_count = content.count("- [ ]") + content.count("- [x]")
        if checkbox_count >= 3:
            patterns.append({
                "description": f"Actionable checklist: {checkbox_count} items",
                "confidence": min(0.75, checkbox_count * 0.1),
                "metadata": {"checkbox_count": checkbox_count},
            })
        
        return patterns
    
    async def _store_pattern(self, db: AsyncSession, pattern: Dict[str, Any]) -> None:
        """Store a learned pattern to the database"""
        from ..models.memory import LearnedPattern
        
        # Check for existing pattern
        existing = await db.execute(
            select(LearnedPattern).where(
                LearnedPattern.role == pattern["role"],
                LearnedPattern.stage_id == pattern["stage_id"],
                LearnedPattern.description == pattern["description"],
            )
        )
        
        existing_pattern = existing.scalar_one_or_none()
        
        if existing_pattern:
            # Update existing pattern
            existing_pattern.frequency += 1
            existing_pattern.confidence = min(
                1.0,
                (existing_pattern.confidence + pattern["confidence"]) / 2 + 0.02
            )
            if pattern["task_id"] not in (existing_pattern.example_task_ids or []):
                examples = existing_pattern.example_task_ids or []
                examples.append(pattern["task_id"])
                existing_pattern.example_task_ids = examples[-20:]
        else:
            # Create new pattern
            new_pattern = LearnedPattern(
                role=pattern["role"],
                stage_id=pattern["stage_id"],
                pattern_type=pattern.get("pattern_type", "general"),
                description=pattern["description"],
                confidence=pattern["confidence"],
                frequency=1,
                example_task_ids=[pattern["task_id"]],
            )
            db.add(new_pattern)
        
        await db.flush()
    
    async def _record_failure(
        self,
        db: AsyncSession,
        task_id: str,
        role: str,
        stage_id: str,
        error: str,
        fix_description: Optional[str] = None,
    ) -> None:
        """Record a task failure for future pattern matching"""
        # Store as a low-confidence pattern (negative example)
        await self._store_pattern(db, {
            "role": role,
            "stage_id": stage_id,
            "task_id": task_id,
            "pattern_type": "failure",
            "description": f"FAILURE: {error[:200]}",
            "confidence": 0.1,  # Low confidence for failures
        })
        
        # Also store the fix if available
        if fix_description:
            await self._store_pattern(db, {
                "role": role,
                "stage_id": stage_id,
                "task_id": task_id,
                "pattern_type": "recovery",
                "description": f"FIX for '{error[:100]}': {fix_description[:200]}",
                "confidence": 0.7,  # Higher confidence for proven fixes
            })
    
    async def _record_recovery_pattern(
        self,
        db: AsyncSession,
        task_id: str,
        role: str,
        stage_id: str,
        error: str,
        fix_description: str,
    ) -> None:
        """Record a recovery pattern (what fixed what)"""
        await self._store_pattern(db, {
            "role": role,
            "stage_id": stage_id,
            "task_id": task_id,
            "pattern_type": "recovery",
            "description": f"FIX: {fix_description[:200]}",
            "confidence": 0.75,
        })
    
    async def _optimize_behavior(
        self,
        db: AsyncSession,
        role: str,
        stage_id: str,
        success: bool,
        quality_score: float,
        tokens_used: int,
        duration_seconds: float,
    ) -> Dict[str, Any]:
        """Optimize agent behavior based on execution feedback"""
        updates = {}
        
        # Track success rate
        if success:
            updates["success_rate"] = "incremented"
        else:
            updates["success_rate"] = "decremented"
        
        # Track quality trends
        if quality_score > 0.8:
            updates["quality_trend"] = "improving"
        elif quality_score < 0.5:
            updates["quality_trend"] = "declining"
        
        # Token efficiency optimization
        if tokens_used > 0:
            efficiency = quality_score / (tokens_used / 1000) if quality_score > 0 else 0
            if efficiency < 0.3:
                updates["suggestion"] = "Consider reducing output verbosity"
            elif efficiency > 0.8:
                updates["suggestion"] = "Excellent token efficiency"
        
        return updates
    
    # ─────────────────────────────────────────────────────────────────────
    # Pattern Retrieval
    # ─────────────────────────────────────────────────────────────────────
    
    async def get_patterns_for_context(
        self,
        db: AsyncSession,
        role: str,
        stage_id: str,
        task_description: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant learned patterns for a given context.
        
        Uses semantic matching to find the most applicable patterns.
        """
        from ..models.memory import LearnedPattern
        
        # Get patterns by role and stage
        result = await db.execute(
            select(LearnedPattern).where(
                LearnedPattern.role == role,
                LearnedPattern.stage_id == stage_id,
                LearnedPattern.confidence >= self._confidence_threshold,
                LearnedPattern.pattern_type != "failure",  # Don't suggest failure patterns
            )
            .order_by(LearnedPattern.confidence.desc())
            .limit(limit * 2)
        )
        
        patterns = result.scalars().all()
        
        # Score patterns by relevance to task description
        scored = []
        for p in patterns:
            relevance = self._calculate_relevance(p.description, task_description)
            scored.append({
                "type": p.pattern_type,
                "description": p.description,
                "confidence": p.confidence,
                "relevance": relevance,
                "frequency": p.frequency or 1,
                "score": (p.confidence * 0.6 + relevance * 0.2 + min(p.frequency or 1, 10) * 0.02),
            })
        
        # Sort by combined score and return top matches
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
    
    async def get_recovery_patterns(
        self,
        db: AsyncSession,
        role: str,
        error_pattern: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find recovery patterns matching a given error.
        Used when an agent encounters an error to suggest fixes.
        """
        from ..models.memory import LearnedPattern
        
        result = await db.execute(
            select(LearnedPattern).where(
                LearnedPattern.role == role,
                LearnedPattern.pattern_type == "recovery",
                LearnedPattern.confidence >= 0.5,
            )
            .order_by(LearnedPattern.confidence.desc())
            .limit(limit * 3)
        )
        
        patterns = result.scalars().all()
        
        # Match error patterns
        matches = []
        for p in patterns:
            similarity = self._calculate_relevance(error_pattern, p.description)
            if similarity > 0.3:
                matches.append({
                    "description": p.description,
                    "confidence": p.confidence,
                    "relevance": similarity,
                    "score": similarity * p.confidence,
                })
        
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:limit]
    
    def _calculate_relevance(self, pattern_desc: str, query: str) -> float:
        """Calculate relevance score between pattern and query"""
        if not pattern_desc or not query:
            return 0.0
        
        # Simple Jaccard-like word overlap
        pattern_words: Set[str] = set(pattern_desc.lower().split())
        query_words: Set[str] = set(query.lower().split())
        
        if not pattern_words or not query_words:
            return 0.0
        
        intersection = pattern_words & query_words
        union = pattern_words | query_words
        
        return len(intersection) / len(union) if union else 0.0
    
    # ─────────────────────────────────────────────────────────────────────
    # Learning Statistics
    # ─────────────────────────────────────────────────────────────────────
    
    async def get_learning_stats(
        self,
        db: AsyncSession,
        role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get learning statistics for dashboard display"""
        from ..models.memory import LearnedPattern
        
        query = select(LearnedPattern)
        if role:
            query = query.where(LearnedPattern.role == role)
        
        result = await db.execute(query)
        patterns = result.scalars().all()
        
        if not patterns:
            return {"total_patterns": 0, "role": role}
        
        # Calculate statistics
        types = {}
        total_confidence = 0
        total_frequency = 0
        
        for p in patterns:
            pt = p.pattern_type or "general"
            types[pt] = types.get(pt, 0) + 1
            total_confidence += p.confidence or 0
            total_frequency += p.frequency or 0
        
        return {
            "total_patterns": len(patterns),
            "role": role,
            "pattern_types": types,
            "avg_confidence": round(total_confidence / len(patterns), 3) if patterns else 0,
            "total_frequency": total_frequency,
            "top_patterns": sorted(
                [{"type": p.pattern_type, "description": p.description[:100], "confidence": p.confidence}
                 for p in patterns if p.confidence and p.confidence >= 0.7],
                key=lambda x: x["confidence"],
                reverse=True,
            )[:5],
        }
    
    async def compute_agent_trust_score(
        self,
        db: AsyncSession,
        role: str,
    ) -> float:
        """
        Compute agent trust score based on learning history.
        
        Formula (inspired by ruflo):
            0.4 × success_rate + 0.2 × avg_quality + 0.2 × pattern_count + 0.2 × consistency
        """
        from ..models.memory import LearnedPattern
        
        result = await db.execute(
            select(LearnedPattern).where(LearnedPattern.role == role)
        )
        patterns = result.scalars().all()
        
        if not patterns:
            return 0.5  # Default neutral trust
        
        # Success patterns vs failure patterns
        success_patterns = [p for p in patterns if p.pattern_type != "failure"]
        failure_patterns = [p for p in patterns if p.pattern_type == "failure"]
        
        total = len(success_patterns) + len(failure_patterns)
        if total == 0:
            return 0.5
        
        # 0.4 × success_rate
        success_rate = len(success_patterns) / total
        success_score = 0.4 * success_rate
        
        # 0.2 × avg_confidence
        avg_confidence = sum(p.confidence or 0 for p in success_patterns) / max(len(success_patterns), 1)
        quality_score = 0.2 * (avg_confidence if avg_confidence > 0 else 0.5)
        
        # 0.2 × pattern_count (normalized)
        pattern_count = min(len(success_patterns), 50) / 50
        count_score = 0.2 * pattern_count
        
        # 0.2 × consistency (high pattern count implies consistency)
        consistency = min(len(patterns) / 10, 1.0)
        consistency_score = 0.2 * consistency
        
        trust = success_score + quality_score + count_score + consistency_score
        
        return round(min(1.0, trust), 3)


# Singleton
_learning_engine: Optional[LearningEngine] = None


def get_learning_engine() -> LearningEngine:
    """Get or create the learning engine singleton"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
