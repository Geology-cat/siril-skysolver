#!/bin/zsh
set -eu
task_source_dir="${0:A:h}"
task_install_dir="$HOME/Library/Application Support/org.siril.Siril/scripts"
mkdir -p "$task_install_dir"
if [[ -f "$task_install_dir/SkySolver.py" ]] && ! cmp -s "$task_source_dir/SkySolver.py" "$task_install_dir/SkySolver.py"; then
    cp -p "$task_install_dir/SkySolver.py" "$task_install_dir/SkySolver.py.backup-$(date +%Y%m%d-%H%M%S)"
fi
cp "$task_source_dir/SkySolver.py" "$task_install_dir/SkySolver.py"
print "インストールしました: $task_install_dir/SkySolver.py"
print "Sirilのコマンド欄で reloadscripts を実行するとメニューに反映されます。"
print "画像を開き、スクリプト → Pythonスクリプト → SkySolver を実行してください。"
print "直接実行する場合: pyscript SkySolver.py"
