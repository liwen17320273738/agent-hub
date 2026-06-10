# 思路：用栈，遇到左括号入栈，遇到右括号出栈。最后栈为空则全部匹配。
def max_depth(s: str) -> int:
    depth = 0
    max_d = 0

    for ch in s:
        if ch == '(':
            depth += 1
            max_d = max(max_d, depth)
        elif ch == ')':
            depth -= 1

    return max_d


# 测试
print(max_depth("(1+(2*3)+((8)/4))+1"))  # 3
print(max_depth("(1)+((2))+(((3)))"))    # 3
print(max_depth("()"))                    # 1
print(max_depth("()(()())"))              # 2
print(max_depth(""))                      # 0
