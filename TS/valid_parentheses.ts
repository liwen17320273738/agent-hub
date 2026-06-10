function isValid(s: string): boolean {
    const pairs: Record<string, string> = {')': '(', ']': '[', '}': '{'};
    const stack: string[] = [];

    for (const ch of s) {
        if (ch in pairs) {
            if (!stack.length || stack[stack.length - 1] !== pairs[ch]) {
                return false;
            }
            stack.pop();
        } else {
            stack.push(ch);
        }
    }

    return stack.length === 0;
}

// 测试
console.log(isValid("()"));        // true
console.log(isValid("()[]{}"));    // true
console.log(isValid("(]"));        // false
console.log(isValid("([])"));      // true
console.log(isValid("["));         // false
