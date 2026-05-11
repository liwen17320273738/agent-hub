"""
/autoplan Command - Automatic Task Orchestration

Automatically decompose a task into sub-tasks, build dependency DAG,
and estimate effort.
"""
import logging
import time
from typing import Any, Dict, List

from . import BaseCommand, CommandArgument, CommandContext, CommandResult, CommandStatus, ExecutionMetrics

logger = logging.getLogger(__name__)


class AutoplanCommand(BaseCommand):
    """
    /autoplan - Automatic Task Orchestration
    
    Decomposes a high-level task description into actionable sub-tasks,
    builds a dependency DAG, and provides effort estimates.
    """
    
    name = "/autoplan"
    description = (
        "Automatically decompose a task into sub-tasks, build a dependency DAG, "
        "and provide effort estimates. Use this when you have a vague idea and "
        "need a structured plan."
    )
    category = "planning"
    
    def get_arguments(self) -> List[CommandArgument]:
        return [
            CommandArgument(
                name="task",
                description="Task description in natural language",
                type="string",
                required=True,
            ),
            CommandArgument(
                name="constraints",
                description="JSON object with constraints (deadline, budget, team_size)",
                type="object",
                required=False,
            ),
            CommandArgument(
                name="template",
                description="Template to use (web_app, api_service, data_pipeline, general)",
                type="string",
                required=False,
                default="general",
                enum=["web_app", "api_service", "data_pipeline", "general"],
            ),
        ]
    
    async def execute(self, ctx: CommandContext) -> CommandResult:
        """Execute the autoplan command"""
        start_time = time.time()
        errors = []
        artifacts = []
        
        try:
            # Extract arguments
            task_description = ctx.arguments.get("task", "")
            constraints = ctx.arguments.get("constraints", {})
            template = ctx.arguments.get("template", "general")
            
            if not task_description:
                return CommandResult(
                    command=self.name,
                    status=CommandStatus.FAILED,
                    errors=["Task description is required"],
                    message="Task description is required",
                )
            
            # Call LeadAgent for task decomposition
            tasks = await self._decompose_task(task_description, template, ctx)
            
            # Build DAG
            dag = self._build_dag(tasks)
            
            # Estimate effort
            estimates = self._estimate_effort(tasks, constraints)
            
            # Combine results
            output = {
                "task_description": task_description,
                "template": template,
                "constraints": constraints,
                "tasks": tasks,
                "dag": dag,
                "estimates": estimates,
                "total_estimated_hours": estimates.get("total_hours", 0),
                "critical_path": self._find_critical_path(dag, tasks),
            }
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return CommandResult(
                command=self.name,
                status=CommandStatus.COMPLETED,
                output=output,
                artifacts=artifacts,
                metrics=ExecutionMetrics(duration_ms=duration_ms),
                message=f"Successfully created plan with {len(tasks)} tasks",
            )
            
        except Exception as e:
            logger.error(f"/autoplan failed: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            return CommandResult(
                command=self.name,
                status=CommandStatus.FAILED,
                errors=[str(e)],
                metrics=ExecutionMetrics(duration_ms=duration_ms),
                message=f"Failed to create plan: {str(e)}",
            )
    
    async def _decompose_task(
        self, task: str, template: str, ctx: CommandContext
    ) -> List[Dict[str, Any]]:
        """Decompose task using LeadAgent"""
        try:
            # Import LeadAgent
            from ..lead_agent import decompose_task
            
            # Decompose the task
            result = await decompose_task(
                task_description=task,
                template=template,
                workspace_id=ctx.workspace_id,
            )
            
            return result.get("tasks", [])
            
        except Exception as e:
            logger.warning(f"LeadAgent decomposition failed, using fallback: {e}")
            # Fallback: simple decomposition
            return self._fallback_decompose(task)
    
    def _fallback_decompose(self, task: str) -> List[Dict[str, Any]]:
        """Fallback task decomposition without LLM"""
        base_tasks = [
            {
                "id": "task-1",
                "name": "Requirements Analysis",
                "description": "Analyze and document requirements",
                "stage": "planning",
                "estimated_hours": 2,
                "dependencies": [],
            },
            {
                "id": "task-2",
                "name": "Architecture Design",
                "description": "Design system architecture",
                "stage": "architecture",
                "estimated_hours": 4,
                "dependencies": ["task-1"],
            },
            {
                "id": "task-3",
                "name": "Implementation",
                "description": "Implement the solution",
                "stage": "development",
                "estimated_hours": 16,
                "dependencies": ["task-2"],
            },
            {
                "id": "task-4",
                "name": "Testing",
                "description": "Write and run tests",
                "stage": "testing",
                "estimated_hours": 8,
                "dependencies": ["task-3"],
            },
            {
                "id": "task-5",
                "name": "Deployment",
                "description": "Deploy to production",
                "stage": "deployment",
                "estimated_hours": 2,
                "dependencies": ["task-4"],
            },
        ]
        
        # Add task-specific task
        base_tasks.insert(0, {
            "id": "task-0",
            "name": f"Understand: {task[:50]}...",
            "description": task,
            "stage": "planning",
            "estimated_hours": 1,
            "dependencies": [],
        })
        
        return base_tasks
    
    def _build_dag(self, tasks: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Build dependency DAG from tasks"""
        dag = {}
        for task in tasks:
            task_id = task.get("id", task.get("name", ""))
            dependencies = task.get("dependencies", [])
            dag[task_id] = dependencies
        return dag
    
    def _estimate_effort(
        self, tasks: List[Dict[str, Any]], constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Estimate effort for tasks"""
        total_hours = sum(task.get("estimated_hours", 0) for task in tasks)
        
        # Calculate parallel execution time
        max_parallel = 3  # Assume max 3 parallel tracks
        parallel_time = total_hours / max_parallel
        
        # Apply constraints
        deadline = constraints.get("deadline")
        team_size = constraints.get("team_size", 1)
        
        adjusted_hours = total_hours / team_size if team_size > 1 else total_hours
        
        return {
            "total_hours": total_hours,
            "parallel_hours": parallel_time,
            "adjusted_hours": adjusted_hours,
            "team_size": team_size,
            "deadline": deadline,
            "phases": self._group_by_phase(tasks),
        }
    
    def _group_by_phase(self, tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        """Group tasks by phase and sum hours"""
        phases = {}
        for task in tasks:
            stage = task.get("stage", "unknown")
            hours = task.get("estimated_hours", 0)
            phases[stage] = phases.get(stage, 0) + hours
        return phases
    
    def _find_critical_path(
        self, dag: Dict[str, List[str]], tasks: List[Dict[str, Any]]
    ) -> List[str]:
        """Find the critical path through the DAG"""
        # Simple critical path: longest sequence of dependencies
        task_map = {t.get("id", t.get("name", "")): t for t in tasks}
        
        def get_depth(task_id: str, visited: set = None) -> int:
            if visited is None:
                visited = set()
            if task_id in visited:
                return 0
            visited.add(task_id)
            
            deps = dag.get(task_id, [])
            if not deps:
                return task_map.get(task_id, {}).get("estimated_hours", 1)
            
            return task_map.get(task_id, {}).get("estimated_hours", 1) + max(
                get_depth(dep, visited) for dep in deps
            )
        
        # Find longest path
        max_depth = 0
        critical_path = []
        for task_id in dag.keys():
            depth = get_depth(task_id)
            if depth > max_depth:
                max_depth = depth
        
        # Reconstruct critical path
        def find_path(task_id: str, target_depth: int, visited: set = None) -> List[str]:
            if visited is None:
                visited = set()
            if task_id in visited:
                return []
            visited.add(task_id)
            
            deps = dag.get(task_id, [])
            if not deps:
                return [task_id] if get_depth(task_id) == target_depth else []
            
            for dep in deps:
                path = find_path(dep, target_depth, visited.copy())
                if path:
                    return path + [task_id]
            
            return []
        
        for task_id in dag.keys():
            path = find_path(task_id, max_depth)
            if len(path) > len(critical_path):
                critical_path = path
        
        return critical_path or list(dag.keys())
