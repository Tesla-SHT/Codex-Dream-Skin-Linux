#!/bin/bash
# Device-local artwork preferences. Refresh active windows without restarting ChatGPT.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
. "$SCRIPT_DIR/common-linux.sh"
. "$SCRIPT_DIR/theme-switch-lock-linux.sh"
ensure_node_runtime
json=false
args=()
for arg in "$@"; do
  if [ "$arg" = "--json" ]; then json=true; else args+=("$arg"); fi
done
command="${args[0]:-toggle}"
case "$command" in
  status|on|off|toggle) [ "${#args[@]}" -le 1 ] || exit 2 ;;
  opacity) [ "${#args[@]}" -eq 2 ] || { printf '用法：dreamskin wallpaper opacity <0..100>\n' >&2; exit 2; } ;;
  *) printf '用法：dreamskin wallpaper on|off|toggle|status|opacity <0..100> [--json]\n' >&2; exit 2 ;;
esac
if [ "$command" != "status" ]; then
  "$NODE" "$SCRIPT_DIR/wallpaper-settings.mjs" --state-root "$STATE_ROOT" check-root
  acquire_theme_switch_lock "$(new_operation_token)"
  trap 'release_theme_switch_lock' EXIT
fi
settings="$("$NODE" "$SCRIPT_DIR/wallpaper-settings.mjs" --state-root "$STATE_ROOT" "$command" "${args[@]:1}" --json)"
session="$(state_field session 2>/dev/null || true)"
applied=false
message='设置已保存，下次启动换肤时生效。'
if [ "$command" = "status" ]; then
  message='拖动滑块会自动保存；关闭背景图保留主题配色。'
elif [ "$session" = "active" ]; then
  port="$(state_field port 2>/dev/null || true)"
  if [ -n "$port" ] && cdp_http_ready "$port"; then
    if "$NODE" "$INJECTOR" --refresh-wallpaper --port "$port" --theme-dir "$THEME_DIR" \
        --animation-settings "$ANIMATION_SETTINGS_PATH" --timeout-ms 8000 >/dev/null 2>&1; then
      applied=true
      message='已保存并应用到当前窗口，无需重启。'
    else
      message='已保存；当前窗口暂未确认应用，下次启动换肤时生效。'
    fi
  fi
elif [ "$session" = "paused" ]; then
  message='已保存，重新启用皮肤时生效；当前保持暂停。'
fi
if [ "$json" = "true" ]; then
  "$NODE" -e 'console.log(JSON.stringify({settings:JSON.parse(process.argv[1]),applied:process.argv[2]==="true",session:process.argv[3],message:process.argv[4]}))' "$settings" "$applied" "$session" "$message"
else
  "$NODE" -e 'const s=JSON.parse(process.argv[1]);console.log(`静态壁纸：${s.enabled?"开启":"关闭"}；图片不透明度 ${Math.round(s.opacity*100)}%；主题配色和布局保留。`)' "$settings"
  [ "$command" = "status" ] || printf '%s\n' "$message"
fi
