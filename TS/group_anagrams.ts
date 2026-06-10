function groupAnagrams(strs: string[]): string[][] {
    const groups = new Map<string, string[]>();

    for (const s of strs) {
        const key = s.split("").sort().join("");
        if (!groups.has(key)) {
            groups.set(key, []);
        }
        groups.get(key)!.push(s);
    }

    return Array.from(groups.values());
}

// 测试
console.log(groupAnagrams(["eat","tea","tan","ate","nat","bat"]));
// [['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]
console.log(groupAnagrams([""]));      // [[""]]
console.log(groupAnagrams(["a"]));     // [["a"]]
