"""
CLI Commands - Base Classes and Schemas

This module provides the foundation for slash commands in Agent Hub.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CommandStatus(str, Enum):
    """Command execution status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Schema Models
# ─────────────────────────────────────────────────────────────────────────────

class CommandArgument(BaseModel):
    """A single command argument definition"""
    name: str = Field(..., description="Argument name")
    description: str = Field(..., description="Argument description")
    type: str = Field(..., description="Argument type (string, number, boolean, array, object)")
    required: bool = Field(False, description="Whether this argument is required")
    default: Optional[Any] = Field(None, description="Default value if optional")
    enum: Optional[List[str]] = Field(None, description="Allowed values for enum type")


class ExecutionMetrics(BaseModel):
    """Metrics from command execution"""
    duration_ms: int = Field(0, description="Execution duration in milliseconds")
    tokens_used: int = Field(0, description="Total tokens consumed")
    cost_usd: float = Field(0.0, description="Estimated cost in USD")
    memory_mb: int = Field(0, description="Peak memory usage")
    calls_made: int = Field(0, description="Number of API calls made")


class Artifact(BaseModel):
    """Command output artifact"""
    type: str = Field(..., description="Artifact type (file, link, data)")
    name: str = Field(..., description="Artifact name")
    path: Optional[str] = Field(None, description="File path if file type")
    url: Optional[str] = Field(None, description="URL if link type")
    content: Optional[str] = Field(None, description="Content if inline type")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class CommandResult(BaseModel):
    """Structured command execution result"""
    command: str = Field(..., description="Command name")
    status: CommandStatus = Field(..., description="Execution status")
    output: Optional[Dict[str, Any]] = Field(None, description="Structured output data")
    artifacts: List[Artifact] = Field(default_factory=list, description="Output artifacts")
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics, description="Execution metrics")
    errors: List[str] = Field(default_factory=list, description="Error messages")
    message: Optional[str] = Field(None, description="Human-readable summary")


class CommandContext(BaseModel):
    """Execution context for commands"""
    session_id: str = Field(..., description="Session identifier")
    user_id: str = Field(..., description="User identifier")
    workspace_id: str = Field(..., description="Workspace identifier")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Command arguments")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class CommandDefinition(BaseModel):
    """Command metadata for registration"""
    name: str = Field(..., description="Command name (e.g., /autoplan)")
    description: str = Field(..., description="Command description")
    arguments: List[CommandArgument] = Field(default_factory=list, description="Argument definitions")
    required_roles: List[str] = Field(default_factory=list, description="Allowed roles")
    examples: List[str] = Field(default_factory=list, description="Usage examples")
    category: str = Field("general", description="Command category")


class ValidationResult(BaseModel):
    """Argument validation result"""
    valid: bool = Field(..., description="Whether validation passed")
    errors: List[str] = Field(default_factory=list, description="Validation error messages")
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")


class ProgressEvent(BaseModel):
    """Progress update event"""
    command: str = Field(..., description="Command name")
    stage: str = Field(..., description="Current execution stage")
    progress: int = Field(..., ge=0, le=100, description="Progress percentage")
    message: Optional[str] = Field(None, description="Stage message")


# ─────────────────────────────────────────────────────────────────────────────
# Base Command Class
# ─────────────────────────────────────────────────────────────────────────────

class BaseCommand(ABC):
    """
    Abstract base class for all CLI commands.
    
    Each command must implement:
    - name: Command name (e.g., "/autoplan")
    - description: Human-readable description
    - execute(): Main execution logic
    - validate(): Argument validation
    
    Optionally implement:
    - get_help(): Custom help text
    """
    
    name: str = ""
    description: str = ""
    category: str = "general"
    
    @abstractmethod
    async def execute(self, ctx: CommandContext) -> CommandResult:
        """
        Execute the command with given context.
        
        Args:
            ctx: Execution context containing arguments and metadata
            
        Returns:
            CommandResult with structured output
        """
        pass
    
    def get_arguments(self) -> List[CommandArgument]:
        """Return the list of command arguments"""
        return []
    
    async def validate(self, args: Dict[str, Any]) -> ValidationResult:
        """
        Validate command arguments.
        
        Args:
            args: Raw arguments to validate
            
        Returns:
            ValidationResult with any errors
        """
        errors = []
        warnings = []
        
        for arg_def in self.get_arguments():
            value = args.get(arg_def.name)
            
            # Check required arguments
            if arg_def.required and value is None:
                errors.append(f"Missing required argument: {arg_def.name}")
            
            # Check enum values
            if value and arg_def.enum and value not in arg_def.enum:
                errors.append(
                    f"Invalid value for {arg_def.name}: {value}. "
                    f"Allowed values: {', '.join(arg_def.enum)}"
                )
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
    
    def get_definition(self) -> CommandDefinition:
        """Get the command definition for registration"""
        return CommandDefinition(
            name=self.name,
            description=self.description,
            arguments=self.get_arguments(),
            required_roles=[],  # Override in subclasses
            examples=[],  # Override in subclasses
            category=self.category,
        )
    
    def get_help(self) -> str:
        """Return help text for this command"""
        args = self.get_arguments()
        args_text = ""
        if args:
            args_text = "\n\nArguments:\n"
            for arg in args:
                req = "(required)" if arg.required else "(optional)"
                default = f" [default: {arg.default}]" if arg.default is not None else ""
                args_text += f"  {arg.name}: {arg.description} {req}{default}\n"
        
        return f"# {self.name}\n\n{self.description}{args_text}"


# ─────────────────────────────────────────────────────────────────────────────
# Command Categories
# ─────────────────────────────────────────────────────────────────────────────

class CommandCategory(str, Enum):
    """Command categories"""
    PLANNING = "planning"      # /autoplan
    REVIEW = "review"          # /review
    QA = "qa"                 # /qa
    SHIP = "ship"             # /ship
    RETROSPECTIVE = "retro"  # /retro
    POWER = "power"          # /careful, /freeze, /guard
    UTILITY = "utility"       # Help, status, etc.
