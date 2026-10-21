#!/bin/bash
# Dream Skin 设置面板启动器（Linux）。
# source common-linux.sh 以复用 STATE_ROOT 等变量与 ensure_node_runtime；
# 选择 Python：优先 ${DREAMSKIN_PYTHON}，否则 command -v python3；用
# `python -c "import tkinter"` 检测，失败时给出 python3-tk 安装说明。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# 开始前检查 parent 目录与面板脚本
if [ ! -d "$SCRIPT_DIR" ]; then
  echo "错误：脚本目录不存在：$SCRIPT_DIR" >&2
  exit 1
fi
PANEL_PY="$SCRIPT_DIR/settings-panel.py"
if [ ! -f "$PANEL_PY" ]; then
  echo "错误：未找到设置面板脚本：$PANEL_PY" >&2
  exit 1
fi

# 复用 common-linux.sh 的 STATE_ROOT 解析与 Node 运行时检测
. "$SCRIPT_DIR/common-linux.sh"
ensure_node_runtime
# 子程序（wallpaper/start/pause 脚本）需从环境读取 NODE
export NODE

# 选择 Python 解释器
if [ -n "${DREAMSKIN_PYTHON:-}" ]; then
  if [ -x "${DREAMSKIN_PYTHON}" ]; then
    PY="${DREAMSKIN_PYTHON}"
  else
    echo "错误：DREAMSKIN_PYTHON 指定的解释器不可用：${DREAMSKIN_PYTHON}" >&2
    if command -v zenity >/dev/null 2>&1; then
      zenity --error --text="DREAMSKIN_PYTHON 指定的解释器不可用：\n\n  ${DREAMSKIN_PYTHON}" 2>/dev/null || true
    fi
    exit 1
  fi
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "未找到 Python 3。请安装：sudo apt install python3 python3-tk" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --text="未找到 Python 3，请安装 python3 与 python3-tk：\n\n  sudo apt install python3 python3-tk" 2>/dev/null || true
  fi
  exit 1
fi

# 检测 tkinter（仅标准库，无 pip 依赖）
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "Python 已安装但缺少 tkinter 模块。请安装：sudo apt install python3-tk" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --text="Python 已安装但缺少 tkinter 模块，请运行：\n\n  sudo apt install python3-tk" 2>/dev/null || true
  fi
  exit 1
fi

exec "$PY" "$PANEL_PY" "$@"
