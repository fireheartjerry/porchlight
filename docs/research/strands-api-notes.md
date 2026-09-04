# Strands 1.54.0 API notes (auto-extracted from installed package)

## Agent.__init__ (self, model: strands.models.model.Model | str | strands.models.routing.router.ModelRouter | None = None, messages: list[strands.types.content.Message] | None = None, tools: list[typing.Union[str, dict[str, str], ForwardRef('ToolProvider'), typing.Any]] | None = None, system_prompt: str | list[strands.types.content.SystemContentBlock] | None = None, structured_output_model: type[pydantic.main.BaseModel] | None = None, callback_handler: collections.abc.Callable[..., typing.Any] | strands.agent.agent._DefaultCallbackHandlerSentinel | None = <strands.agent.agent._DefaultCallbackHandlerSentinel object at 0x105d93e60>, conversation_manager: strands.agent.conversation_manager.conversation_manager.ConversationManager | None = None, record_direct_tool_call: bool = True, load_tools_from_directory: bool = False, trace_attributes: collections.abc.Mapping[str, str | bool | float | int | list[str] | list[bool] | list[float] | list[int] | collections.abc.Sequence[str] | collections.abc.Sequence[bool] | collections.abc.Sequence[int] | collections.abc.Sequence[float]] | None = None, *, agent_id: str | None = None, name: str | None = None, description: str | None = None, state: strands.types.json_dict.JSONSerializableDict | dict | None = None, context_manager: Optional[Literal['auto', 'agentic']] = None, plugins: list[strands.plugins.plugin.Plugin] | None = None, hooks: list[strands.hooks.registry.HookProvider | strands.hooks.registry.HookCallback] | None = None, interventions: list[strands.interventions.handler.InterventionHandler] | None = None, session_manager: strands.session.session_manager.SessionManager | None = None, memory_manager: strands.memory.memory_manager.MemoryManager | strands.memory.types.MemoryManagerConfig | None = None, structured_output_prompt: str | None = None, tool_executor: strands.tools.executors._executor.ToolExecutor | None = None, retry_strategy: strands.event_loop._retry.ModelRetryStrategy | strands.agent.agent._DefaultRetryStrategySentinel | None = <strands.agent.agent._DefaultRetryStrategySentinel object at 0x107a2a270>, concurrent_invocation_mode: strands.types.agent.ConcurrentInvocationMode = <ConcurrentInvocationMode.THROW: 'throw'>, checkpointing: bool = False, sandbox: strands.sandbox.base.Sandbox | None = None, storage: strands.storage.storage.Storage | None = None)
Initialize the Agent with the specified configuration.

Args:
    model: Provider for running inference or a string representing the model-id for Bedrock to use.
        May also be a ``ModelRouter``, whose first candidate is resolved to a concrete model and
        exposed as ``agent.model``. Defaults to strands.models.BedrockModel if None.
    messages: List of initial messages to pre-load into the conversation.
        Defaults to an empty list if None.
    tools: List of tools to make available to the agent.
        Can be specified as:

        - String tool names (e.g., "retrieve")
        - File paths (e.g., "/path/to/tool.py")
        - Imported Python modules (e.g., from strands_tools import current_time)
        - Dictionaries with name/path keys (e.g., {"name": "tool_name", "path": "/path/to/tool.py"})
        - ToolProvider instances for managed tool collections
        - Functions decorated with `@strands.tool` decorator
        - Agent instances (auto-wrapped via `agent.as_tool()` with defaults)

        If provided, only these tools will be available. If None, all tools will be available.
    system_prompt: System prompt to guide model behavior.
        Can be a string or a list of SystemContentBlock objects for advanced features like caching.
        If None, the model will behave according to its default settings.
    structured_output_model: Pydantic model type(s) for structured output.
        When specified, all agent calls will attempt to return structured output of this type.
        This can be overridden on the agent invocation.
        Defaults to None (no structured output).
    callback_handler: Callback for processing events as they happen during agent execution.
        If not provided (using the default), a new PrintingCallbackHandler instance is created.
        If explicitly set to None, null_callback_handler is used.
    conversation_manager: Manager for conversation history and context window.
        Defaults to strands.agent.conversation_manager.SlidingWindowConversationManager if None.
    record_direct_tool_call: Whether to record direct tool calls in message history.
        Defaults to True.
    load_tools_from_directory: Whether to load and automatically reload tools in the `./tools/` directory.
        Defaults to False.
    trace_attributes: Custom trace attributes to apply to the agent's trace span.
    agent_id: Optional ID for the agent, useful for session management and multi-agent scenarios.
        Defaults to "default".
    name: name of the Agent
        Defaults to "Strands Agents".
    description: description of what the Agent does
        Defaults to None.
    state: stateful information for the agent. Can be either an AgentState object, or a json serializable dict.
        Defaults to an empty AgentState object.
    context_manager: Context management strategy. When set to ``"auto"``, composes
        a ContextOffloader plugin (max_result_tokens=1500, preview_tokens=750) with a
        SummarizingConversationManager (summary_ratio=0.3, compression_threshold=0.85)
        using benchmark-validated defaults. If ``conversation_manager`` is also provided,
        the user's conversation manager is used instead. Defaults to None (no context management).

        Note: The offloader uses in-memory storage by default. When an agent-level
        ``storage`` is provided, the offloader uses that instead. Alternatively,
        provide an explicit ``ContextOffloader`` with its own storage via the
        ``plugins`` parameter.
    plugins: List of Plugin instances to extend agent functionality.
        Plugins are initialized with the agent instance after construction and can register hooks,
        modify agent attributes, or perform other setup tasks.
        Defaults to None.
    hooks: Hooks to be added to the agent hook registry. Accepts HookProvider instances
        or plain callable hook callbacks (functions with typed event parameters).
        Defaults to None.
    interventions: List of InterventionHandler instances for agent control.
        Handlers are evaluated in registration order at each lifecycle event.
        Cheapest handlers (authorization, guardrails) should be listed first;
        expensive ones (LLM steering) last. Deny short-circuits immediately,
        Guide feedback accumulates across handlers.
        Defaults to None.
    session_manager: Manager for handling agent sessions including conversation history and state.
        If provided, enables session-based persistence and state management.
    memory_manager: Cross-session memory manager, as a
        :class:`~strands.memory.MemoryManager` or a
        :class:`~strands.memory.MemoryManagerConfig` (auto-wrapped). Registers its
        memory tools; the synchronous ``Agent(...)`` entry point flushes pending
        extraction after each invocation. Defaults to None.
    structured_output_prompt: Custom prompt message used when forcing structured output.
        When using structured output, if the model doesn't automatically use the output tool,
        the agent sends a follow-up message to request structured formatting. This parameter
        allows customizing that message.
        Defaults to "You must format the previous response as structured output."
    tool_executor: Definition of tool execution strategy (e.g., sequential, concurrent, etc.).
    retry_strategy: Strategy for retrying model calls on throttling or other transient errors.
        Defaults to ModelRetryStrategy with max_attempts=6, initial_delay=4s, max_delay=240s.
        Implement a custom HookProvider for custom retry logic, or pass None to disable retries.
    concurrent_invocation_mode: Mode controlling concurrent invocation behavior.
        Defaults to "throw" which raises ConcurrencyException if concurrent invocation is attempted.
        Set to "unsafe_reentrant" to skip lock acquisition entirely, allowing concurrent invocations.
        Warning: "unsafe_reentrant" makes no guarant

## Agent.__call__ (self, prompt: str | list[strands.types.content.ContentBlock] | list[strands.types.interrupt.InterruptResponseContent] | list[strands.types.content.Message] | None = None, *, invocation_state: dict[str, typing.Any] | None = None, structured_output_model: type[pydantic.main.BaseModel] | None = None, structured_output_prompt: str | None = None, idempotency_token: Any = None, limits: strands.types.agent.Limits | None = None, cancel_signal: threading.Event | None = None, **kwargs: Any) -> strands.agent.agent_result.AgentResult
Process a natural language prompt through the agent's event loop.

This method implements the conversational interface with multiple input patterns:
- String input: `agent("hello!")`
- ContentBlock list: `agent([{"text": "hello"}, {"image": {...}}])`
- Message list: `agent([{"role": "user", "content": [{"text": "hello"}]}])`
- No input: `agent()` - uses existing conversation history

Args:
    prompt: User input in various formats:
        - str: Simple text input
        - list[ContentBlock]: Multi-modal content blocks
        - list[Message]: Complete messages with roles
        - None: Use existing conversation history
    invocation_state: Additional parameters to pass through the event loop.
    structured_output_model: Pydantic model type(s) for structured output (overrides agent default).
    structured_output_prompt: Custom prompt for forcing structured output (overrides agent default).
    idempotency_token: Dedup token for THROW mode (ignored in UNSAFE_REENTRANT). If a matching
        token is already inflight, this call blocks until the original finishes, then gets its
        final result — only the result, not the streamed events, though ``callback_handler``
        still fires once with it. Matched by ``==`` (any equatable object; need not be hashable).
        Raises ``IdempotencyAbortedError`` if the original is aborted before producing a result.
    limits: Per-invocation budget caps (turns / output_tokens / total_tokens).
        See :class:`~strands.types.agent.Limits`. When a cap is reached, the loop
        terminates gracefully at the next turn boundary with a corresponding
        ``stop_reason`` (e.g. ``"limit_turns"``); no exception is raised. Token
        caps are soft — a single oversized model response can overshoot the budget
        by one turn, since checks run at turn boundaries, not within a model call.
    cancel_signal: Caller-owned event that cancels this invocation. Use it when cancellation is
        driven from outside the ag

## Agent.invoke_async (self, prompt: str | list[strands.types.content.ContentBlock] | list[strands.types.interrupt.InterruptResponseContent] | list[strands.types.content.Message] | None = None, *, invocation_state: dict[str, typing.Any] | None = None, structured_output_model: type[pydantic.main.BaseModel] | None = None, structured_output_prompt: str | None = None, idempotency_token: Any = None, limits: strands.types.agent.Limits | None = None, cancel_signal: threading.Event | None = None, **kwargs: Any) -> strands.agent.agent_result.AgentResult
## Agent.stream_async (self, prompt: str | list[strands.types.content.ContentBlock] | list[strands.types.interrupt.InterruptResponseContent] | list[strands.types.content.Message] | None = None, *, invocation_state: dict[str, typing.Any] | None = None, structured_output_model: type[pydantic.main.BaseModel] | None = None, structured_output_prompt: str | None = None, idempotency_token: Any = None, limits: strands.types.agent.Limits | None = None, cancel_signal: threading.Event | None = None, **kwargs: Any) -> collections.abc.AsyncIterator[typing.Any]
Process a natural language prompt and yield events as an async iterator.

This method provides an asynchronous interface for streaming agent events with multiple input patterns:
- String input: Simple text input
- ContentBlock list: Multi-modal content blocks
- Message list: Complete messages with roles
- No input: Use existing conversation history

Args:
    prompt: User input in various formats:
        - str: Simple text input
        - list[ContentBlock]: Multi-modal content blocks
        - list[Message]: Complete messages with roles
        - None: Use existing conversation history
    invocation_state: Additional parameters to pass through the event loop.
    structured_output_model: Pydantic model type(s) for structured output (overrides agent default).
    structured_output_prompt: Custom prompt for forcing structured output (overrides agent default).
    idempotency_token: Dedup token for THROW mode (ignored in UNSAFE_REENTRANT). If a matching
        token is already inflight, this call blocks until the original finishes, then gets its
        final result — only the result, not the streamed events, though ``callback_handler``
        still fires once with it. Matched by ``==`` (any equatable object; need not be hashable).
        Raises ``IdempotencyAbortedError`` if the original is aborted before producing a result.
    limits: Per-invocation budget caps (turns / output_tokens / total_tokens).
        See :class:`~strands.types.agent.Limits`. When a cap is reached, the loop
        terminates gracefully at the next turn boundary with a corresponding
        ``stop_reason`` (e.g. ``"limit_turns"``); no exception is raised. Token
        caps are soft — a single oversized model response can overshoot the budget
        by one turn, since checks run at turn boundaries, not within a model call.
    cancel_signal: Caller-owned event that cancels this invocation. Use it when cancellation is
        driven from outside the agent — a client disconnect, a reques
## Agent public methods: ['ToolCaller', 'add_hook', 'as_tool', 'cancel', 'cancel_signal', 'cleanup', 'concurrent_invocation_mode', 'invoke_async', 'load_snapshot', 'sandbox', 'session_id', 'storage', 'stream_async', 'structured_output', 'structured_output_async', 'system_prompt', 'system_prompt_content', 'take_snapshot', 'tool', 'tool_names']

## BedrockModel.__init__ (self, *, boto_session: boto3.session.Session | None = None, boto_client_config: botocore.config.Config | None = None, region_name: str | None = None, endpoint_url: str | None = None, **model_config: Unpack[strands.models.bedrock.BedrockModel.BedrockConfig])
Initialize provider instance.

Args:
    boto_session: Boto Session to use when calling the Bedrock Model.
    boto_client_config: Configuration to use when creating the Bedrock-Runtime Boto Client.
    region_name: AWS region to use for the Bedrock service.
        Defaults to the AWS_REGION environment variable if set, or "us-west-2" if not set.
    endpoint_url: Custom endpoint URL for VPC endpoints (PrivateLink)
    **model_config: Configuration options for the Bedrock model.
## BedrockModel.BedrockConfig keys:
{'context_window_limit': int | None, 'additional_args': dict[str, typing.Any] | None, 'additional_request_fields': dict[str, typing.Any] | None, 'additional_response_field_paths': list[str] | None, 'cache_prompt': str | None, 'cache_config': strands.models.model.CacheConfig | None, 'cache_tools': str | strands.models.model.CacheToolsConfig | None, 'guardrail_id': str | None, 'guardrail_trace': typing.Optional[typing.Literal['enabled', 'disabled', 'enabled_full']], 'guardrail_stream_processing_mode': typing.Optional[typing.Literal['sync', 'async']], 'guardrail_version': str | None, 'guardrail_redact_input': bool | None, 'guardrail_redact_input_message': str | None, 'guardrail_redact_output': bool | None, 'guardrail_redact_output_message': str | None, 'guardrail_latest_message': bool | None, 'max_tokens': int | None, 'model_id': <class 'str'>, 'include_tool_result_status': typing.Union[typing.Literal['auto'], bool, NoneType], 'service_tier': str | None, 'stop_sequences': list[str] | None, 'streaming': bool | None, 'strict_tools': bool | None, 'temperature': float | None, 'top_p': float | None, 'use_native_token_count': <class 'bool'>}

## GraphBuilder methods
add_node (self, executor: strands.agent.base.AgentBase | strands.multiagent.base.MultiAgentBase, node_id: str | None = None) -> strands.multiagent.graph.GraphNode
    Add an AgentBase or MultiAgentBase instance as a node to the graph.
add_edge (self, from_node: str | strands.multiagent.graph.GraphNode, to_node: str | strands.multiagent.graph.GraphNode, condition: collections.abc.Callable[['GraphState'], bool] | strands.multiagent.graph.EdgeConditionWithContext | None = None) -> strands.multiagent.graph.GraphEdge
    Add an edge between two nodes with optional condition function.

    The condition can be either:
    - A legacy callable: Callable[[GraphState], bool] - receives only graph state
    - A new-style callable: EdgeConditionWithContext - receives graph state and invocation_state
set_entry_point (self, node_id: str) -> 'GraphBuilder'
    Set a node as an entry point for graph execution.
build (self) -> 'Graph'
    Build and validate the graph with configured settings.
set_execution_timeout (self, timeout: float) -> 'GraphBuilder'
    Set total execution timeout.

    Args:
        timeout: Total execution timeout in seconds (None for no limit)
set_max_node_executions (self, max_executions: int) -> 'GraphBuilder'
    Set maximum number of node executions allowed.

    Args:
        max_executions: Maximum total node executions (None for no limit)
set_node_timeout (self, timeout: float) -> 'GraphBuilder'
    Set individual node execution timeout.

    Args:
        timeout: Individual node timeout in seconds (None for no limit)
reset_on_revisit (self, enabled: bool = True) -> 'GraphBuilder'
    Control whether nodes reset their state when revisited.

    When enabled, nodes will reset their messages and state to initial values
    each time they are revisited (re-executed). This is useful for stateless
    behavior where nodes should start fresh on each revisit.

    Args:
        enabled: Whether to reset node state when revisited (default: True)

## Graph public: ['add_hook', 'deserialize_state', 'invoke_async', 'serialize_state', 'stream_async']
## GraphState fields: {'task': str | list[strands.types.content.ContentBlock] | list[strands.types.interrupt.InterruptResponseContent], 'status': <enum 'Status'>, 'completed_nodes': set['GraphNode'], 'failed_nodes': set['GraphNode'], 'interrupted_nodes': set['GraphNode'], 'execution_order': list['GraphNode'], 'start_time': <class 'float'>, 'results': dict[str, strands.multiagent.base.NodeResult], 'accumulated_usage': <class 'strands.types.event_loop.Usage'>, 'accumulated_metrics': <class 'strands.types.event_loop.Metrics'>, 'execution_count': <class 'int'>, 'execution_time': <class 'int'>, 'total_nodes': <class 'int'>, 'edges': list[tuple['GraphNode', 'GraphNode']], 'entry_points': list['GraphNode']}
## GraphResult fields: {'total_nodes': <class 'int'>, 'completed_nodes': <class 'int'>, 'failed_nodes': <class 'int'>, 'interrupted_nodes': <class 'int'>, 'execution_order': list['GraphNode'], 'edges': list[tuple['GraphNode', 'GraphNode']], 'entry_points': list['GraphNode']}

## Swarm.__init__ (self, nodes: list[strands.agent.agent.Agent], *, entry_point: strands.agent.agent.Agent | None = None, max_handoffs: int = 20, max_iterations: int = 20, execution_timeout: float = 900.0, node_timeout: float = 300.0, repetitive_handoff_detection_window: int = 0, repetitive_handoff_min_unique_agents: int = 0, session_manager: strands.session.session_manager.SessionManager | None = None, hooks: list[strands.hooks.registry.HookProvider] | None = None, id: str = 'default_swarm', trace_attributes: collections.abc.Mapping[str, str | bool | float | int | list[str] | list[bool] | list[float] | list[int] | collections.abc.Sequence[str] | collections.abc.Sequence[bool] | collections.abc.Sequence[int] | collections.abc.Sequence[float]] | None = None, plugins: list[strands.plugins.multiagent_plugin.MultiAgentPlugin] | None = None) -> None
Initialize Swarm with agents and configuration.

Args:
    id: Unique swarm id (default: "default_swarm")
    nodes: List of nodes (e.g. Agent) to include in the swarm
    entry_point: Agent to start with. If None, uses the first agent (default: None)
    max_handoffs: Maximum handoffs to agents and users (default: 20)
    max_iterations: Maximum node executions within the swarm (default: 20)
    execution_timeout: Total execution timeout in seconds (default: 900.0)
    node_timeout: Individual node timeout in seconds (default: 300.0)
    repetitive_handoff_detection_window: Number of recent nodes to check for repetitive handoffs
        Disabled by default (default: 0)
    repetitive_handoff_min_unique_agents: Minimum unique agents required in recent sequence
        Disabled by default (default: 0)
    session_manager: Session manager for persisting graph state and execution history (default: None)
    hooks: List of hook providers for monitoring and extending graph execution behavior (default: None)
    trace_attributes: Custom trace attributes to apply to the agent's trace span (default: None)
    plugins: List of multi-agent plugins for extending swarm behavior (default: None)

## MultiAgentBase abstract: ['add_hook', 'deserialize_state', 'invoke_async', 'serialize_state', 'stream_async']

## tool decorator (func: collections.abc.Callable[~P, ~R] | None = None, description: str | None = None, inputSchema: dict | None = None, name: str | None = None, context: bool | str = False) -> Union[strands.tools.decorator.DecoratedFunctionTool[~P, ~R], collections.abc.Callable[[collections.abc.Callable[~P, ~R]], strands.tools.decorator.DecoratedFunctionTool[~P, ~R]]]
Decorator that transforms a Python function into a Strands tool.

This decorator seamlessly enables a function to be called both as a regular Python function and as a Strands tool.
It extracts metadata from the function's signature, docstring, and type hints to generate an OpenAPI-compatible tool
specification.

When decorated, a function:

1. Still works as a normal function when called directly with arguments
2. Processes tool use API calls when provided with a tool use dictionary
3. Validates inputs against the function's type hints and parameter spec
4. Formats return values according to the expected Strands tool result format
5. Provides automatic error handling and reporting

The decorator can be used in two ways:
- As a simple decorator: `@tool`
- With parameters: `@tool(name="custom_name", description="Custom description")`

Args:
    func: The function to decorate. When used as a simple decorator, this is the function being decorated.
        When used with parameters, this will be None.
    description: Optional custom description to override the function's docstring.
    inputSchema: Optional custom JSON schema to override the automatically generated schema.
    name: Optional custom name to override the function's name.
    context: When provided, places an object in the designated parameter. If True, the param name
        defaults to 'tool_context', or if an override is needed, set context equal to a string to designate
        the param name.

Returns:
    An AgentTool that also mimics the original function when invoked

Example:
    ```python
    @tool
    def my_tool(name: str, count: int = 1) -> str:
        # Does something useful with the provided parameters.
        #
        # Parameters:
        #   name: The name to process
        #   count: Number of times to process (default: 1)
        #
        # Returns:
        #   A message with the result
        return f"Processed {name} {count} times"

    agent = Agent(tools=[my_tool])
    agent.my_tool(name="example", count=3)
    # Returns: {
    #   "toolUseId": "123",
    #   "status": "success",
    #   "content": [{"text": "Processed example 3 times"}]
    # }
    ```

Example with parameters:
    ```python
    @tool(name="custom_tool", description="A tool with a custom name and description", context=True)
    def my_tool(name: str, count: int = 1, tool_context: ToolContext) -> str:
        tool_id = tool_context["tool_use"]["toolUseId"]
        return f"Processed {name} {count} ti

## Session managers
FileSessionManager (self, session_id: str, storage_dir: str | None = None, **kwargs: Any)
    Initialize FileSession with filesystem storage.

    Args:
        session_id: ID for the session.
            ID is not allowed to contain path separators (e.g., a/b).
        storage_dir: Directory for local filesystem storage.
            Defaults to a user-private ``~/.strands/sessions/`` directory.
        **kwargs: Additional keyword arguments for future extensibility.
S3SessionManager (self, session_id: str, bucket: str, prefix: str = '', boto_session: boto3.session.Session | None = None, boto_client_config: botocore.config.Config | None = None, region_name: str | None = None, endpoint_url: str | None = None, **kwargs: Any)
    Initialize S3SessionManager with S3 storage.

    Args:
        session_id: ID for the session
            ID is not allowed to contain path separators (e.g., a/b).
        bucket: S3 bucket name (required)
        prefix: S3 key prefix for storage organization
        boto_session: Optional boto3 session
        boto_client_config: Optional boto3 client configuration
        region_name: AWS region for S3 storage
        endpoint_url: Custom endpoint URL for S3-compatible storage backends (e.g., MinIO, LocalStack)
            or VPC endpoints (PrivateLink)
        **kwargs: Additional keyword arguments for future extensibility.
SnapshotSessionManager (self, session_id: str = 'default-session', *, storage: strands.storage.storage.Storage | None = None, save_latest_on: Literal['message', 'invocation', 'trigger'] = 'invocation', snapshot_trigger: strands.session.snapshot_session_manager.SnapshotTrigger | None = None, **kwargs: Any) -> None
    Initialize the snapshot session manager.

    Args:
        session_id: Unique session identifier. Must not contain path separators.
        storage: Unified storage backend that persists snapshot blobs. When None,
            resolves from the agent-level ``storage`` during initialization; if no
            agent-level storage is available, falls back to
            :class:`~strands.storage.local_file_storage.LocalFileStorage`.
        save_latest_on: When to overwrite ``snapshot_latest``. See :data:`SaveLatestStrategy`.
        snapshot_trigger: Optional callback invoked after each invocation; when it
            returns True an immutable snapshot is appended for checkpointing. An immutable
            snapshot can also be forced at any point via :meth:`save_snapshot`.
        **kwargs: Additional keyword arguments for future exte
RepositorySessionManager (self, session_id: str, session_repository: strands.session.session_repository.SessionRepository, **kwargs: Any)
    Initialize the RepositorySessionManager.

    If no session with the specified session_id exists yet, it will be created
    in the session_repository.

    Args:
        session_id: ID to use for the session. A new session with this id will be created if it does
            not exist in the repository yet
        session_repository: Underlying session repository to use to store the sessions state.
        **kwargs: Additional keyword arguments for future extensibility.

## Hook events and fields
AfterInvocationEvent {'invocation_state': dict[str, typing.Any], 'result': 'AgentResult | None', 'resume': str | list[strands.types.content.ContentBlock] | list[strands.types.interrupt.InterruptResponseContent] | list[strands.types.content.Message] | None} | writable: ['result']
AfterModelCallEvent {'invocation_state': dict[str, typing.Any], 'stop_response': strands.hooks.events.AfterModelCallEvent.ModelStopResponse | None, 'exception': Exception | None, 'retry': <class 'bool'>} | writable: ['retry']
AfterMultiAgentInvocationEvent {'source': 'MultiAgentBase', 'invocation_state': dict[str, typing.Any] | None} | writable: []
AfterNodeCallEvent {'source': 'MultiAgentBase', 'node_id': <class 'str'>, 'invocation_state': dict[str, typing.Any] | None} | writable: []
AfterToolCallEvent {'selected_tool': strands.types.tools.AgentTool | None, 'tool_use': <class 'strands.types.tools.ToolUse'>, 'invocation_state': dict[str, typing.Any], 'result': <class 'strands.types.tools.ToolResult'>, 'exception': Exception | None, 'cancel_message': str | None, 'duration': float | None, 'retry': <class 'bool'>} | writable: ['selected_tool', 'tool_use', 'result', 'retry']
AfterToolsEvent {'message': <class 'strands.types.content.Message'>, 'invocation_state': dict[str, typing.Any], 'end_turn': bool | str | list[strands.types.content.ContentBlock]} | writable: []
AgentInitializedEvent {} | writable: []
BaseHookEvent {} | writable: []
BeforeInvocationEvent {'invocation_state': dict[str, typing.Any], 'messages': list[strands.types.content.Message] | None, 'cancel': bool | str} | writable: ['cancel']
BeforeModelCallEvent {'invocation_state': dict[str, typing.Any], 'projected_input_tokens': int | None, 'cancel': bool | str} | writable: ['cancel']
BeforeMultiAgentInvocationEvent {'source': 'MultiAgentBase', 'invocation_state': dict[str, typing.Any] | None} | writable: []
BeforeNodeCallEvent {'source': 'MultiAgentBase', 'node_id': <class 'str'>, 'invocation_state': dict[str, typing.Any] | None, 'cancel_node': bool | str} | writable: []
BeforeToolCallEvent {'selected_tool': strands.types.tools.AgentTool | None, 'tool_use': <class 'strands.types.tools.ToolUse'>, 'invocation_state': dict[str, typing.Any], 'cancel_tool': bool | str} | writable: ['cancel_tool', 'selected_tool', 'tool_use']
BeforeToolsEvent {'message': <class 'strands.types.content.Message'>, 'invocation_state': dict[str, typing.Any], 'cancel': bool | str} | writable: ['cancel']
HookEvent {'agent': 'Agent'} | writable: []
MessageAddedEvent {'message': <class 'strands.types.content.Message'>} | writable: []
MultiAgentInitializedEvent {'source': 'MultiAgentBase', 'invocation_state': dict[str, typing.Any] | None} | writable: []

## Conversation managers
['ConversationManager', 'NullConversationManager', 'ProactiveCompressionConfig', 'SlidingWindowConversationManager', 'SummarizingConversationManager', 'compression', 'conversation_manager', 'null_conversation_manager', 'sliding_window_conversation_manager', 'summarizing_conversation_manager']

## interventions / memory_manager / checkpointing / context_manager
strands.interventions ['Confirm', 'Deny', 'Guide', 'InterventionAction', 'InterventionHandler', 'OnError', 'Proceed', 'Transform', 'actions', 'handler', 'registry']
strands.memory ['AddMessagesContext', 'AggregateMemoryError', 'ExtractionConfig', 'ExtractionResult', 'ExtractionTrigger', 'ExtractionTriggerContext', 'Extractor', 'ExtractorContext', 'InjectionConfig', 'InjectionContext', 'InjectionFormatContext', 'InjectionQueryContext', 'InjectionTrigger', 'IntervalTrigger', 'InvocationTrigger', 'MemoryAddOptions', 'MemoryAddToolConfig', 'MemoryContentBlockType', 'MemoryEntry', 'MemoryInjectionConfig', 'MemoryManager', 'MemoryManagerConfig', 'MemoryMessageFilter', 'MemorySearchOptions', 'MemoryStore', 'MemoryStoreConfig', 'MemoryToolConfig', 'ModelExtractor', 'SearchOptions', 'extraction', 'memory_manager', 'types']
strands.checkpointing ERR No module named 'strands.checkpointing'
strands.agent.context_manager ERR No module named 'strands.agent.context_manager'
strands.context ERR No module named 'strands.context'
strands.storage ['InMemoryStorage', 'LocalFileStorage', 'S3Storage', 'Storage', 'in_memory_storage', 'local_file_storage', 's3_storage', 'search', 'storage']
strands.sandbox ['ExecutionResult', 'FileInfo', 'LANGUAGE_PATTERN', 'OutputFile', 'PosixShellSandbox', 'Sandbox', 'StreamChunk', 'StreamType', 'base', 'constants', 'errors', 'not_a_sandbox_local_environment', 'posix_shell', 'stream_process', 'types']

## telemetry
['EventLoopMetrics', 'MetricsClient', 'StrandsTelemetry', 'Trace', 'Tracer', 'config', 'get_tracer', 'metrics', 'metrics_constants', 'metrics_to_string', 'tracer']
StrandsTelemetry ['setup_console_exporter', 'setup_meter', 'setup_otlp_exporter']

## MCP
['MCPAgentTool', 'MCPClient', 'MCPClientCredentials', 'MCPServerConfig', 'MCPTransport', 'TasksConfig', 'ToolFilters', 'mcp_agent_tool', 'mcp_client', 'mcp_instrumentation', 'mcp_tasks', 'mcp_types']
MCPClient.__init__ (self, transport_callable: collections.abc.Callable[[], contextlib.AbstractAsyncContextManager[tuple[anyio.streams.memory.MemoryObjectReceiveStream[mcp.shared.message.SessionMessage | Exception], anyio.streams.memory.MemoryObjectSendStream[mcp.shared.message.SessionMessage]] | tuple[anyio.streams.memory.MemoryObjectReceiveStream[mcp.shared.message.SessionMessage | Exception], anyio.streams.memory.MemoryObjectSendStream[mcp.shared.message.SessionMessage], collections.abc.Callable[[], str | None]]]] | None = None, *, url: str | None = None, headers: dict[str, str] | None = None, auth: strands.tools.mcp.mcp_types.MCPClientCredentials | None = None, auth_provider: httpx.Auth | None = None, startup_timeout: int = 30, tool_filters: strands.tools.mcp.mcp_client.ToolFilters | None = None, prefix: str | None = None, application_name: str | None = None, application_version: str | None = None, continue_on_error: bool = False, elicitation_callback: mcp.client.session.ElicitationFnT | None = None, progress_callback: mcp.shared.session.ProgressFnT | None = None, tasks_config: strands.tools.mcp.mcp_tasks.TasksConfig | None = None) -> None

## types.content ContentBlock/Message:
['Any', 'AudioContent', 'CachePoint', 'CitationsContentBlock', 'ContentBlock', 'ContentBlockDelta', 'ContentBlockStart', 'ContentBlockStartToolUse', 'ContentBlockStop', 'DeltaContent', 'DocumentContent', 'GuardContent', 'GuardContentText', 'ImageContent', 'Literal', 'Message', 'MessageMetadata', 'Messages', 'Metrics', 'NotRequired', 'ReasoningContentBlock', 'ReasoningTextBlock', 'Role', 'SystemContentBlock', 'SystemPrompt', 'ToolResult', 'ToolUse', 'TypedDict', 'Usage', 'VideoContent', 'get_message_metadata', 'split_system_prompt', 'uuid']

## strands_tools.agent_core_memory
Tool for managing memories in Bedrock AgentCore Memory Service.

This module provides Bedrock AgentCore Memory capabilities with memory record
creation and retrieval.

Key Features:
------------
1. Event Management:
   • create_event: Store events in memory sessions

2. Memory Record Operations:
   • retrieve_memory_records: Semantic search for extracted memories
   • list_memory_records: List all memory records
   • get_memory_record: Get specific memory record
   • delete_memory_record: Delete memory records

Usage Examples:
--------------
```python
from strands import Agent
from strands_tools.agent_core_memory import AgentCoreMemoryToolProvider

# Initialize with required parameters
provider = AgentCoreMemoryToolProvider(
    memory_id="memory-123abc",  # Required
    actor_id="user-456",        # Required
    session_id="session-789",   # Required
    namespace="default",        # Required
)

agent = Agent(tools=provider.tools)

# Create a memory using the default IDs from initialization
agent.tool.agent_core_memory(
    action="record",
    content="Hello, Remeber that my current hobby is knitting?"
)

# Search memory records using the default namespace from initialization
agent.tool.agent_core_memory(
    action="retrieve",
    query="user preferences"
)
```

## strands_tools.handoff_to_user
User handoff tool for Strands Agent.

This module provides functionality to hand off control from the agent to the user,
allowing for human intervention in automated workflows. It's particularly useful for:

1. Getting user confirmation before proceeding with critical actions
2. Requesting additional information that the agent cannot determine
3. Allowing users to review and approve agent decisions
4. Creating interactive workflows where human input is required
5. Debugging and troubleshooting by pausing execution for user review

Usage with Strands Agent:
```python
from strands import Agent
from strands_tools import handoff_to_user

agent = Agent(tools=[handoff_to_user])

# Request user input and continue
response = agent.tool.handoff_to_user(
    message="I need your approval to proceed with deleting these files. Type 'yes' to confirm.",
    breakout_of_loop=False
)

# Stop execution and hand off to user
agent.tool.handoff_to_user(
    message="Task completed. Please review the results and take any necessary follow-up actions.",
    breakout_of_loop=True
)
```

The handoff tool can either pause for user input or completely stop the event loop,
depending on the breakout_of_loop parameter.

## bedrock_agentcore package
['_utils', 'config_bundle', 'evaluation', 'gateway', 'identity', 'knowledge_base', 'memory', 'payments', 'policy', 'runtime', 'services', 'tools']
BedrockAgentCoreApp ['add_async_task', 'add_exception_handler', 'add_middleware', 'add_route', 'async_task', 'build_middleware_stack', 'clear_forced_ping_status', 'complete_async_task', 'entrypoint', 'force_ping_status', 'get_async_task_info', 'get_current_ping_status', 'host', 'mount', 'ping', 'routes', 'run', 'url_path_for', 'websocket']
Decorator to register a function as the main entrypoint.

Invocation payloads are passed to the registered function unchanged. Applications should validate input
before forwarding it to an agent framework.

Args:
    func: The function to register as entrypoint

Returns:
    The decorated function with added serve method
memory: ['client', 'constants', 'controlplane', 'integrations', 'models', 'session']
integrations: ['strands']
AgentCoreMemorySessionManager (self, agentcore_memory_config: bedrock_agentcore.memory.integrations.strands.config.AgentCoreMemoryConfig, region_name: Optional[str] = None, boto_session: Optional[boto3.session.Session] = None, boto_client_config: Optional[botocore.config.Config] = None, *, converter: Optional[type[bedrock_agentcore.memory.integrations.strands.converters.protocol.MemoryConverter]] = None, **kwargs: Any)
AgentCore Memory-based session manager for Bedrock AgentCore Memory integration.

This session manager integrates Strands agents with Amazon Bedrock AgentCore Memory,
providing seamless synchronization between Strands' session management and Bedrock's
short-term and long-term memory capabilities.

Key Features:
- Automatic synchronization of conversation messages to Bedrock AgentCore Memory events
- Loading of conversation history from short-term memory during agent initialization
- Integration with long-term memory for context injection into agent state
- Support for custom retrieval configurations per namespace
- Consistent with existing Strands Session managers (such as: FileSessionManager, S3SessionManager)
AgentCoreMemoryConfig {'memory_id': <class 'str'>, 'session_id': <class 'str'>, 'actor_id': <class 'str'>, 'retrieval_config': typing.Optional[typing.Dict[str, bedrock_agentcore.memory.integrations.strands.config.RetrievalConfig]], 'batch_size': <class 'int'>, 'flush_interval_seconds': typing.Optional[float], 'context_tag': <class 'str'>, 'filter_restored_tool_context': <class 'bool'>, 'default_metadata': typing.Optional[typing.Dict[str, typing.Any]], 'metadata_provider': typing.Optional[typing.Callable[[], typing.Dict[str, typing.Any]]], 'persistence_mode': <enum 'PersistenceMode'>, 'async_mode': <class 'bool'>}
MemoryClient methods: ['add_custom_episodic_strategy', 'add_custom_episodic_strategy_and_wait', 'add_custom_semantic_strategy', 'add_custom_semantic_strategy_and_wait', 'add_episodic_strategy', 'add_episodic_strategy_and_wait', 'add_semantic_strategy', 'add_semantic_strategy_and_wait', 'add_strategy', 'add_summary_strategy', 'add_summary_strategy_and_wait', 'add_user_preference_strategy', 'add_user_preference_strategy_and_wait', 'create_blob_event', 'create_event', 'create_memory', 'create_memory_and_wait', 'create_or_get_memory', 'delete_memory', 'delete_memory_and_wait', 'delete_strategy', 'fork_conversation', 'get_conversation_tree', 'get_last_k_turns', 'get_memory_status', 'get_memory_strategies', 'list_branch_events', 'list_branches', 'list_events', 'list_memories', 'merge_branch_context', 'modify_strategy', 'process_turn_with_llm', 'retrieve_memories', 'save_conversation', 'update_memory_strategies', 'update_memory_strategies_and_wait', 'wait_for_memories']
