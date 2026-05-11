"""
Command Router - Central dispatcher for CLI commands

Routes command requests to appropriate command handlers
and manages command lifecycle.
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from sse_starlette.sse import EventSourceResponse

from . import (
    BaseCommand,
    CommandContext,
    CommandDefinition,
    CommandResult,
    ValidationResult,
    ProgressEvent,
)
from .autoplan import AutoplanCommand
from .review import ReviewCommand
from .qa import QACommand

logger = logging.getLogger(__name__)


class CommandRegistry:
    """
    Central registry for all CLI commands.
    
    Maintains a dictionary of command name -> Command instance mappings
    and provides lookup, validation, and execution services.
    """
    
    def __init__(self):
        self._commands: Dict[str, BaseCommand] = {}
        self._initialized = False
    
    def initialize(self) -> None:
        """Initialize the command registry with all available commands"""
        if self._initialized:
            return
        
        # Register all commands
        self.register(AutoplanCommand())
        self.register(ReviewCommand())
        self.register(QACommand())
        
        # TODO: Register more commands
        # self.register(ShipCommand())
        # self.register(RetroCommand())
        
        self._initialized = True
        logger.info(f"Command registry initialized with {len(self._commands)} commands")
    
    def register(self, command: BaseCommand) -> None:
        """Register a command"""
        if not command.name:
            raise ValueError("Command must have a name")
        
        self._commands[command.name] = command
        logger.debug(f"Registered command: {command.name}")
    
    def get(self, name: str) -> Optional[BaseCommand]:
        """Get a command by name"""
        return self._commands.get(name)
    
    def list_commands(self) -> List[CommandDefinition]:
        """List all registered commands"""
        return [cmd.get_definition() for cmd in self._commands.values()]
    
    def get_command_definitions(self) -> Dict[str, CommandDefinition]:
        """Get command definitions as a dictionary"""
        return {name: cmd.get_definition() for name, cmd in self._commands.items()}
    
    async def execute(
        self,
        command_name: str,
        arguments: Dict,
        context: CommandContext,
    ) -> CommandResult:
        """
        Execute a command with validation.
        
        Args:
            command_name: Name of the command to execute
            arguments: Command arguments
            context: Execution context
            
        Returns:
            CommandResult with execution output
            
        Raises:
            ValueError: If command not found or validation fails
        """
        # Get command
        command = self.get(command_name)
        if not command:
            raise ValueError(f"Unknown command: {command_name}")
        
        # Validate arguments
        validation = await command.validate(arguments)
        if not validation.valid:
            return CommandResult(
                command=command_name,
                status="failed",
                errors=validation.errors,
                message=f"Validation failed: {', '.join(validation.errors)}",
            )
        
        # Execute
        return await command.execute(context)
    
    def help(self, command_name: Optional[str] = None) -> str:
        """Get help text for a command or all commands"""
        if command_name:
            command = self.get(command_name)
            if not command:
                return f"Unknown command: {command_name}"
            return command.get_help()
        
        # List all commands
        lines = ["# Available Commands\n"]
        for name, cmd in self._commands.items():
            lines.append(f"- **{name}**: {cmd.description}")
        
        return "\n".join(lines)


# Singleton instance
_command_registry: Optional[CommandRegistry] = None


def get_command_registry() -> CommandRegistry:
    """Get or create the command registry singleton"""
    global _command_registry
    if _command_registry is None:
        _command_registry = CommandRegistry()
        _command_registry.initialize()
    return _command_registry


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Router
# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/commands", tags=["commands"])


@router.get("")
async def list_commands():
    """List all available commands"""
    registry = get_command_registry()
    return {
        "commands": registry.get_command_definitions(),
        "count": len(registry._commands),
    }


@router.get("/{command_name}")
async def get_command(command_name: str):
    """Get details for a specific command"""
    registry = get_command_registry()
    command = registry.get(command_name)
    
    if not command:
        raise HTTPException(status_code=404, detail=f"Command not found: {command_name}")
    
    return command.get_definition()


@router.get("/{command_name}/help")
async def get_command_help(command_name: str):
    """Get help text for a command"""
    registry = get_command_registry()
    help_text = registry.help(command_name)
    
    if "Unknown command" in help_text:
        raise HTTPException(status_code=404, detail=help_text)
    
    return {"help": help_text}


@router.post("/execute")
async def execute_command(
    command: str,
    arguments: Dict = {},
    session_id: str = "default",
    user_id: str = "anonymous",
    workspace_id: str = "default",
):
    """
    Execute a command.
    
    - **command**: Command name (e.g., "/autoplan")
    - **arguments**: Command arguments as JSON object
    - **session_id**: Session identifier
    - **user_id**: User identifier
    - **workspace_id**: Workspace identifier
    """
    registry = get_command_registry()
    
    context = CommandContext(
        session_id=session_id,
        user_id=user_id,
        workspace_id=workspace_id,
        arguments=arguments,
    )
    
    try:
        result = await registry.execute(command, arguments, context)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
