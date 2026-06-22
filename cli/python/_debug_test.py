import sys
from unittest.mock import MagicMock, patch
from io import StringIO
from rich.console import Console
from mem0_cli.core.wrapper import build_command_context
from mem0_cli.core.requests import build_delete_payload, build_delete_all_payload
from mem0_cli.core.renderers import (
    render_delete_result,
    render_delete_all_result,
)

# --- test_delete_single ---
print("=== test_delete_single ===")
buf = StringIO()
console = Console(file=buf, force_terminal=False, width=120, color_system=None)
err_buf = StringIO()
err_console = Console(file=err_buf, stderr=True, force_terminal=False, width=120, color_system=None)

mock_backend = MagicMock()
mock_backend.delete.return_value = True

ctx = build_command_context(
    command_name='delete',
    backend=mock_backend,
    config=None,
    output='text',
)

payload = build_delete_payload(memory_id='abc-123', dry_run=False)
print('payload:', payload)
result = mock_backend.delete(**payload)
print('result:', result)
with (
    patch('mem0_cli.core.renderers.console', console),
    patch('mem0_cli.core.renderers._core_err_console', err_console),
):
    render_delete_result(ctx.render_ctx, result, memory_id='abc-123', dry_run=False)
print('stdout:', repr(buf.getvalue()))
print('stderr:', repr(err_buf.getvalue()))
print()

# --- test_delete_all_force ---
print("=== test_delete_all_force ===")
buf2 = StringIO()
console2 = Console(file=buf2, force_terminal=False, width=120, color_system=None)
err_buf2 = StringIO()
err_console2 = Console(file=err_buf2, stderr=True, force_terminal=False, width=120, color_system=None)

ctx2 = build_command_context(
    command_name='delete_all',
    backend=mock_backend,
    config=None,
    output='text',
    user_id='alice',
)
payload2 = build_delete_all_payload(
    scope=ctx2.ids.as_dict(),
    all_project=False,
    all_=False,
    dry_run=False,
)
print('payload2:', payload2)
result2 = mock_backend.delete(**payload2)
print('result2:', result2)
with (
    patch('mem0_cli.core.renderers.console', console2),
    patch('mem0_cli.core.renderers._core_err_console', err_console2),
):
    render_delete_all_result(ctx2.render_ctx, result2, dry_run=False)
print('stdout2:', repr(buf2.getvalue()))
print('stderr2:', repr(err_buf2.getvalue()))
