"""
Swarm Coordination Engine - Multi-agent Swarm Orchestration.

Inspired by ruflo's swarm coordination system, this module enables:
- Queen-led hierarchical coordination
- Consensus-based task allocation  
- Trust scoring and agent reputation
- Adaptive topology switching (hierarchical / mesh / gossip)
"""
from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SwarmTopology(str, Enum):
    """Swarm communication topology"""
    HIERARCHICAL = "hierarchical"  # Queen-led tree structure
    MESH = "mesh"                  # All-to-all communication
    GOSSIP = "gossip"             # Epidemic/gossip protocol
    ADAPTIVE = "adaptive"          # Auto-select based on task


class ConsensusMethod(str, Enum):
    """Consensus algorithms for agent decisions"""
    MAJORITY = "majority"          # Simple majority vote
    WEIGHTED = "weighted"          # Trust-weighted vote
    RAFT = "raft"                  # Raft-like leader consensus
    BYZANTINE = "byzantine"       # Byzantine fault tolerance


@dataclass
class SwarmAgent:
    """An agent in the swarm"""
    id: str
    role: str
    trust_score: float = 0.5
    status: str = "idle"  # idle, busy, error, offline
    capabilities: List[str] = field(default_factory=list)
    task_count: int = 0
    success_count: int = 0
    avg_quality: float = 0.0
    last_active: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SwarmTask:
    """A task to be allocated in the swarm"""
    id: str
    description: str
    required_capabilities: List[str] = field(default_factory=list)
    priority: int = 1  # 1-latest, 5-highest
    estimated_effort: float = 1.0  # hours
    dependencies: List[str] = field(default_factory=list)
    assigned_agent: Optional[str] = None
    status: str = "pending"


@dataclass
class SwarmDecision:
    """Result of a swarm decision process"""
    method: ConsensusMethod
    result: Any
    votes: Dict[str, Any]
    confidence: float
    quorum_reached: bool
    dissenting_agents: List[str] = field(default_factory=list)


class SwarmCoordinator:
    """
    Swarm Coordinator - manages multi-agent swarm orchestration.
    
    Architecture:
    ┌──────────────────────────────────────────────────────────┐
    │                    Swarm Coordinator                      │
    ├──────────────────────────────────────────────────────────┤
    │  ┌──────────────┐  ┌────────────┐  ┌────────────────┐   │
    │  │  Queen Agent  │  │ Consensus  │  │  Task Router   │   │
    │  │  (decider)    │  │  Engine    │  │  (allocator)   │   │
    │  └──────┬───────┘  └─────┬──────┘  └───────┬────────┘   │
    │         │               │                  │             │
    │         └───────────────┼──────────────────┘             │
    │                         ▼                                │
    │               ┌─────────────────┐                       │
    │               │  Agent Registry │                       │
    │               │  (trust scores)  │                      │
    │               └─────────────────┘                       │
    └──────────────────────────────────────────────────────────┘
    """
    
    def __init__(self):
        self._agents: Dict[str, SwarmAgent] = {}
        self._tasks: Dict[str, SwarmTask] = {}
        self._topology: SwarmTopology = SwarmTopology.HIERARCHICAL
        self._queen_id: Optional[str] = None
        self._consensus_method: ConsensusMethod = ConsensusMethod.WEIGHTED
    
    # ─────────────────────────────────────────────────────────────
    # Agent Management
    # ─────────────────────────────────────────────────────────────
    
    def register_agent(
        self,
        agent_id: str,
        role: str,
        capabilities: Optional[List[str]] = None,
        trust_score: float = 0.5,
    ) -> SwarmAgent:
        """Register an agent in the swarm"""
        agent = SwarmAgent(
            id=agent_id,
            role=role,
            trust_score=trust_score,
            capabilities=capabilities or [],
        )
        self._agents[agent_id] = agent
        
        # Elect a queen if none exists
        if self._queen_id is None or self._agents.get(self._queen_id) is None:
            self._elect_queen()
        
        logger.info(f"Agent {agent_id} ({role}) registered in swarm")
        return agent
    
    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the swarm"""
        self._agents.pop(agent_id, None)
        
        # Reassign any tasks
        for task in self._tasks.values():
            if task.assigned_agent == agent_id:
                task.assigned_agent = None
                task.status = "pending"
        
        # Re-elect queen if needed
        if self._queen_id == agent_id:
            self._elect_queen()
        
        logger.info(f"Agent {agent_id} removed from swarm")
    
    def update_agent_trust(self, agent_id: str, trust_score: float) -> None:
        """Update an agent's trust score"""
        if agent_id in self._agents:
            old_trust = self._agents[agent_id].trust_score
            # Exponential moving average
            self._agents[agent_id].trust_score = old_trust * 0.7 + trust_score * 0.3
            logger.debug(f"Agent {agent_id} trust: {old_trust:.2f} → {self._agents[agent_id].trust_score:.2f}")
    
    def _elect_queen(self) -> Optional[str]:
        """Elect the queen agent (highest trust score)"""
        if not self._agents:
            self._queen_id = None
            return None
        
        # Queen is the agent with highest trust score
        queen = max(self._agents.values(), key=lambda a: a.trust_score)
        self._queen_id = queen.id
        logger.info(f"Queen elected: {queen.id} ({queen.role}, trust={queen.trust_score:.2f})")
        return queen.id
    
    # ─────────────────────────────────────────────────────────────
    # Task Allocation
    # ─────────────────────────────────────────────────────────────
    
    def add_task(self, task: SwarmTask) -> SwarmTask:
        """Add a task to the swarm"""
        self._tasks[task.id] = task
        return task
    
    def allocate_tasks(self) -> List[SwarmTask]:
        """Allocate pending tasks to the best-suited agents"""
        allocated = []
        
        # Sort by priority (highest first)
        pending = sorted(
            [t for t in self._tasks.values() if t.status == "pending" and not t.assigned_agent],
            key=lambda t: t.priority,
            reverse=True,
        )
        
        for task in pending:
            best_agent = self._find_best_agent(task)
            if best_agent:
                task.assigned_agent = best_agent.id
                task.status = "allocated"
                best_agent.task_count += 1
                allocated.append(task)
                logger.info(f"Task '{task.id}' allocated to {best_agent.id} ({best_agent.role})")
        
        return allocated
    
    def _find_best_agent(self, task: SwarmTask) -> Optional[SwarmAgent]:
        """Find the best agent for a task using trust-weighted scoring"""
        candidates = []
        
        for agent in self._agents.values():
            if agent.status != "idle":
                continue
            
            # Calculate match score
            score = 0.0
            
            # Capability match
            if task.required_capabilities:
                matched = set(task.required_capabilities) & set(agent.capabilities)
                if not matched:
                    continue  # Must match at least one capability
                score += len(matched) / len(task.required_capabilities) * 0.4
            
            # Trust score weight
            score += agent.trust_score * 0.3
            
            # Success rate weight
            if agent.task_count > 0:
                score += (agent.success_count / agent.task_count) * 0.2
            
            # Availability (fewer tasks = higher score)
            score += max(0, (10 - agent.task_count) / 10) * 0.1
            
            if score > 0:
                candidates.append((score, agent))
        
        if not candidates:
            return None
        
        # Return highest-scoring agent
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    
    # ─────────────────────────────────────────────────────────────
    # Consensus
    # ─────────────────────────────────────────────────────────────
    
    async def reach_consensus(
        self,
        question: str,
        options: List[Any],
        method: Optional[ConsensusMethod] = None,
    ) -> SwarmDecision:
        """
        Reach consensus among swarm agents on a decision.
        
        Args:
            question: The decision question
            options: Available options to vote on
            method: Consensus method (defaults to weighted)
            
        Returns:
            SwarmDecision with the consensus result
        """
        method = method or self._consensus_method
        votes = {}
        
        # Collect votes (in production, this would be async agent calls)
        for agent in self._agents.values():
            if agent.status != "idle":
                continue
            
            # Simulate voting based on trust and role
            if method == ConsensusMethod.WEIGHTED:
                vote = self._weighted_vote(agent, options)
            elif method == ConsensusMethod.MAJORITY:
                vote = self._majority_vote(agent, options)
            else:
                vote = self._weighted_vote(agent, options)
            
            if vote is not None:
                votes[agent.id] = {
                    "vote": vote,
                    "weight": agent.trust_score,
                    "role": agent.role,
                }
        
        if not votes:
            return SwarmDecision(
                method=method,
                result=None,
                votes={},
                confidence=0.0,
                quorum_reached=False,
            )
        
        # Tally votes
        tally: Dict[str, float] = {}
        for agent_id, v in votes.items():
            weight = v["weight"]
            vote_value = str(v["vote"])
            tally[vote_value] = tally.get(vote_value, 0) + weight
        
        # Find winner
        if tally:
            winner = max(tally, key=tally.get)
            total_weight = sum(tally.values())
            winner_weight = tally[winner]
            confidence = winner_weight / total_weight if total_weight > 0 else 0
            quorum = len(votes) >= max(1, len(self._agents) // 2)
            
            # Identify dissenting agents
            dissenting = [aid for aid, v in votes.items() if str(v["vote"]) != winner]
            
            return SwarmDecision(
                method=method,
                result=winner,
                votes=votes,
                confidence=round(confidence, 3),
                quorum_reached=quorum,
                dissenting_agents=dissenting,
            )
        
        return SwarmDecision(
            method=method,
            result=None,
            votes=votes,
            confidence=0.0,
            quorum_reached=False,
        )
    
    def _weighted_vote(self, agent: SwarmAgent, options: List[Any]) -> Optional[Any]:
        """Weighted vote based on agent specialization"""
        if not options:
            return None
        
        # Simple: pick option that best matches agent's role
        for opt in options:
            opt_str = str(opt).lower()
            if agent.role.lower() in opt_str:
                return opt
        
        # Default: pick first option
        return options[0]
    
    def _majority_vote(self, agent: SwarmAgent, options: List[Any]) -> Optional[Any]:
        """Simple majority vote"""
        if not options:
            return None
        # Each agent just picks based on its capabilities
        return options[hash(agent.id) % len(options)]
    
    # ─────────────────────────────────────────────────────────────
    # Topology Management
    # ─────────────────────────────────────────────────────────────
    
    def set_topology(self, topology: SwarmTopology) -> None:
        """Change swarm topology"""
        self._topology = topology
        logger.info(f"Swarm topology changed to: {topology}")
    
    def get_topology(self) -> SwarmTopology:
        """Get current topology"""
        return self._topology
    
    def get_routing_table(self) -> Dict[str, List[str]]:
        """Generate routing table based on current topology"""
        agents = list(self._agents.keys())
        
        if self._topology == SwarmTopology.HIERARCHICAL:
            # Queen connects to all, others only to queen
            routing = {self._queen_id: agents.copy()} if self._queen_id else {}
            for aid in agents:
                if aid != self._queen_id:
                    routing[aid] = [self._queen_id] if self._queen_id else []
            return routing
        
        elif self._topology == SwarmTopology.MESH:
            # All-to-all
            return {aid: [a for a in agents if a != aid] for aid in agents}
        
        elif self._topology == SwarmTopology.GOSSIP:
            # Each agent connects to 3 random peers
            import random
            routing = {}
            for aid in agents:
                peers = [a for a in agents if a != aid]
                routing[aid] = random.sample(peers, min(3, len(peers)))
            return routing
        
        return {}
    
    # ─────────────────────────────────────────────────────────────
    # Swarm Statistics
    # ─────────────────────────────────────────────────────────────
    
    def get_swarm_stats(self) -> Dict[str, Any]:
        """Get swarm statistics"""
        agents = list(self._agents.values())
        tasks = list(self._tasks.values())
        
        return {
            "agent_count": len(agents),
            "task_count": len(tasks),
            "topology": self._topology,
            "queen_id": self._queen_id,
            "consensus_method": self._consensus_method,
            "agents": [
                {
                    "id": a.id,
                    "role": a.role,
                    "trust_score": a.trust_score,
                    "status": a.status,
                    "task_count": a.task_count,
                }
                for a in agents
            ],
            "tasks": [
                {
                    "id": t.id,
                    "description": t.description[:80],
                    "status": t.status,
                    "priority": t.priority,
                    "assigned_agent": t.assigned_agent,
                }
                for t in tasks
            ][:20],
            "pending_tasks": sum(1 for t in tasks if t.status == "pending"),
            "active_tasks": sum(1 for t in tasks if t.status in ("allocated", "running")),
        }


# In-memory swarm instances per workspace
_swarms: Dict[str, SwarmCoordinator] = {}


def get_swarm(workspace_id: str = "default") -> SwarmCoordinator:
    """Get or create a swarm for a workspace"""
    if workspace_id not in _swarms:
        _swarms[workspace_id] = SwarmCoordinator()
    return _swarms[workspace_id]


def delete_swarm(workspace_id: str) -> None:
    """Delete a swarm"""
    _swarms.pop(workspace_id, None)
