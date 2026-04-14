#!/bin/bash
# Agent Hub — Interactive Configuration
# Usage: bash scripts/configure.sh

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

BLUE='\033[94m'
GREEN='\033[92m'
YELLOW='\033[93m'
RESET='\033[0m'

echo -e "\n${BLUE}═══ Agent Hub 配置向导 ═══${RESET}\n"

update_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
    echo -e "  ${GREEN}✓${RESET} ${key} 已更新"
}

echo -e "${BLUE}[1] LLM API Key${RESET}"
echo "  选择你的 LLM 提供商:"
echo "  1) 智谱 GLM (推荐国内)"
echo "  2) DeepSeek"
echo "  3) OpenAI"
echo "  4) Anthropic Claude"
echo "  5) 跳过 (使用本地 Ollama)"
echo ""
read -p "  选择 [1-5]: " llm_choice

case $llm_choice in
    1)
        echo -e "  ${YELLOW}获取地址: https://bigmodel.cn/usercenter/apikeys${RESET}"
        read -p "  输入 ZHIPU_API_KEY: " zhipu_key
        if [ -n "$zhipu_key" ]; then
            update_env "ZHIPU_API_KEY" "$zhipu_key"
        fi
        ;;
    2)
        echo -e "  ${YELLOW}获取地址: https://platform.deepseek.com/api_keys${RESET}"
        read -p "  输入 DEEPSEEK_API_KEY: " ds_key
        if [ -n "$ds_key" ]; then
            update_env "DEEPSEEK_API_KEY" "$ds_key"
        fi
        ;;
    3)
        read -p "  输入 OPENAI_API_KEY: " oai_key
        if [ -n "$oai_key" ]; then
            update_env "OPENAI_API_KEY" "$oai_key"
        fi
        ;;
    4)
        read -p "  输入 ANTHROPIC_API_KEY: " ant_key
        if [ -n "$ant_key" ]; then
            update_env "ANTHROPIC_API_KEY" "$ant_key"
        fi
        ;;
    5)
        echo -e "  ${GREEN}✓${RESET} 使用 Ollama 本地模型"
        ;;
esac

echo ""
echo -e "${BLUE}[2] 部署平台${RESET}"
echo -e "  ${YELLOW}获取 Vercel Token: https://vercel.com/account/tokens${RESET}"
read -p "  输入 VERCEL_TOKEN (回车跳过): " vercel_token
if [ -n "$vercel_token" ]; then
    update_env "VERCEL_TOKEN" "$vercel_token"
fi

echo ""
echo -e "${BLUE}[3] 验证配置${RESET}"
python3 "$ROOT/scripts/setup-check.py"

echo -e "${GREEN}配置完成！运行后端: cd backend && uvicorn app.main:app --reload --port 8787${RESET}"
