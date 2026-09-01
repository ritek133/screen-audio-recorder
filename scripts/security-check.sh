#!/usr/bin/env bash
#
# カスタムセキュリティチェックスクリプト
#
# gitleaks がカバーしないプロジェクト固有のパターン（個人情報・ローカルパス）を
# PR の差分に対して検出する。検出時は exit 1 でジョブを失敗させる。
#
# 要件: SEC-2（個人情報検出）／SEC-5（ローカルパス検出）／SEC-6（差分スキャン・false positive 対策）
# 設計書: 2A.3 カスタムチェックスクリプト／2A.4 除外ルール
#
# 使い方:
#   scripts/security-check.sh [BASE_REF]
#     BASE_REF を省略した場合は環境変数 BASE_REF、さらに省略時は origin/main を使用する。
#
# 移植性のため POSIX 寄りの bash + grep -E（基本正規表現拡張）で実装している。

set -uo pipefail

# ---------------------------------------------------------------------------
# 差分対象ファイルの決定
# ---------------------------------------------------------------------------

# 比較基準（ベース）ブランチ。CI では PR のベースブランチを渡す想定。
BASE_REF="${1:-${BASE_REF:-origin/main}}"

# 差分ファイル一覧を取得する。
# CI（GitHub Actions）ではベース ref との差分を、ローカルではステージ済み/作業中の
# 変更を対象にできるよう、取得に失敗した場合は git diff HEAD にフォールバックする。
get_changed_files() {
    if git rev-parse --verify --quiet "${BASE_REF}" >/dev/null 2>&1; then
        git diff --name-only --diff-filter=ACMR "${BASE_REF}"...HEAD
    else
        # ベース ref が解決できない場合は直近コミットとの差分を対象にする
        git diff --name-only --diff-filter=ACMR HEAD~1 2>/dev/null || git diff --name-only --diff-filter=ACMR HEAD
    fi
}

# ---------------------------------------------------------------------------
# 除外判定
# ---------------------------------------------------------------------------

# false positive 対策として検出対象から除外するパス（設計書 2A.4）。
# - tests/            : テストコード内のモック値・ダミーデータ
# - docs/             : ドキュメント内のプレースホルダー例
# - .gitleaks.toml    : gitleaks 設定ファイル自体
# - .gitignore        : gitignore ファイル自体
# - scripts/security-check.sh : 本スクリプト自身（検出パターンを含むため）
is_excluded_path() {
    case "$1" in
        tests/*|*/tests/*) return 0 ;;
        docs/*|*/docs/*) return 0 ;;
        .gitleaks.toml) return 0 ;;
        .gitignore) return 0 ;;
        scripts/security-check.sh) return 0 ;;
        *) return 1 ;;
    esac
}

# バイナリ判定（バイナリファイルは grep の対象から外す）
is_binary() {
    # grep -Iq はバイナリなら非ゼロを返す
    grep -Iq . "$1" 2>/dev/null && return 1 || return 0
}

# ---------------------------------------------------------------------------
# 検出パターン
# ---------------------------------------------------------------------------
# 各要素は "ラベル|正規表現(grep -E)" の形式。
PATTERNS=(
    "メールアドレス|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    "Windows ローカルパス|[A-Za-z]:\\\\Users\\\\[^\\\\]+"
    "Unix ローカルパス|/home/[a-zA-Z0-9_]+/"
    "電話番号（日本）|0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}"
    "マイナンバー形式|[0-9]{4}[[:space:]]?[0-9]{4}[[:space:]]?[0-9]{4}"
)

# メールアドレスの除外（プレースホルダー扱い）。
# example.com / placeholder を含む行は検出しない（設計書 2A.3 除外対象）。
is_email_placeholder() {
    # $1 = マッチ行
    printf '%s' "$1" | grep -Eiq 'example\.com|placeholder'
}

# マイナンバー形式はバージョン番号や連番と誤検知しやすいため、
# 明らかに数値の羅列（区切りなしの 12 桁、または空白/スペース区切り）だけを対象にし、
# ドット区切り（バージョン番号）等は除外する。
# ここでは grep -E のパターンでスペース/連続数字のみを許容しているため追加除外は行わない。

# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

found=0

mapfile -t files < <(get_changed_files)

if [ "${#files[@]}" -eq 0 ]; then
    echo "変更ファイルが検出されませんでした。スキップします。"
    exit 0
fi

echo "===== カスタムセキュリティチェック開始 ====="
echo "ベース ref: ${BASE_REF}"
echo "検査対象ファイル数: ${#files[@]}"
echo ""

for file in "${files[@]}"; do
    # ファイルが存在しない（削除など）場合はスキップ
    [ -f "${file}" ] || continue

    # 除外パス
    if is_excluded_path "${file}"; then
        continue
    fi

    # バイナリはスキップ
    if is_binary "${file}"; then
        continue
    fi

    for entry in "${PATTERNS[@]}"; do
        label="${entry%%|*}"
        regex="${entry#*|}"

        # マッチ行を行番号付きで取得
        while IFS= read -r match_line; do
            [ -z "${match_line}" ] && continue

            # match_line 例: "12:foo@example.com bar"
            line_no="${match_line%%:*}"
            content="${match_line#*:}"

            # メールアドレスのプレースホルダー除外
            if [ "${label}" = "メールアドレス" ] && is_email_placeholder "${content}"; then
                continue
            fi

            echo "[検出] ${file}:${line_no}"
            echo "  種別: ${label}"
            echo "  内容: ${content}"
            echo ""
            found=1
        done < <(grep -nE "${regex}" "${file}" 2>/dev/null)
    done
done

echo "===== カスタムセキュリティチェック終了 ====="

if [ "${found}" -ne 0 ]; then
    echo ""
    echo "個人情報またはローカルパスが検出されました。上記の該当箇所を修正してください。"
    echo "（テスト用のダミー値・ドキュメントのプレースホルダーは tests/ や docs/ 配下に配置するか、"
    echo " メールアドレスは example.com / placeholder を使用してください）"
    exit 1
fi

echo "問題は検出されませんでした。"
exit 0
