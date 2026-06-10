function maxDepth(s: string): number {
    let depth = 0;
    let maxD = 0;

    for (const ch of s) {
        if (ch === '(') {
            depth++;
            maxD = Math.max(maxD, depth);
        } else if (ch === ')') {
            depth--;
        }
    }

    return maxD;
}

// 测试
console.log(maxDepth("(1+(2*3)+((8)/4))+1"));  // 3
console.log(maxDepth("(1)+((2))+(((3)))"));    // 3
console.log(maxDepth("()"));                    // 1
console.log(maxDepth("()(()())"));              // 2
console.log(maxDepth(""));                      // 0
