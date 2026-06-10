
#思路：用栈，遇到左括号入栈，遇到右括号检查栈顶是否匹配。最后栈为空则全部匹配。
from typing import List

def is_valid(s: str) -> bool:
    pairs = {')': '(', ']': '[', '}': '{'}
    stack: List[str] = []

    for ch in s:
        if ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
        else:
            stack.append(ch)

    return not stack


# 测试
print(is_valid("()"))        # True
print(is_valid("()[]{}"))    # True
print(is_valid("(]"))        # False
print(is_valid("([])"))      # True
print(is_valid("["))         # False
