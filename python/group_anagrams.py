from typing import List
from collections import defaultdict

def group_anagrams(strs: List[str]) -> List[List[str]]:
    groups = defaultdict(list)

    for s in strs:
        # 排序后的字符串作为 key
        key = "".join(sorted(s))
        groups[key].append(s)

    return list(groups.values())


# 测试
print(group_anagrams(["eat","tea","tan","ate","nat","bat"]))
# [['eat', 'tea', 'ate'], ['tan', 'nat'], ['bat']]
print(group_anagrams([""]))      # [[""]]
print(group_anagrams(["a"]))     # [["a"]]
