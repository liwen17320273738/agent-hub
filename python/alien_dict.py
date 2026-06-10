#总结 DAG 题三步走：

# 建图 — 邻接表 graph[u].append(v)
# 算入度 — indegree[v] += 1
# Kahn BFS — 入度为 0 的入队，出队减邻居入度，最后检查 count == node

from typing import List
from collections import deque, defaultdict

def alien_order(words: List[str]) -> str:
    # 建图
    graph = defaultdict(set)
    indegree = {ch: 0 for word in words for ch in word}

    for w1, w2 in zip(words, words[1:]):
        # 非法：前缀相同但前一个更长（如 ["abc", "ab"]）
        if len(w1) > len(w2) and w1[:len(w2)] == w2:
            return ""
        for c1, c2 in zip(w1, w2):
            if c1 != c2:
                if c2 not in graph[c1]:
                    graph[c1].add(c2)
                    indegree[c2] += 1
                break

    # Kahn
    q = deque([ch for ch in indegree if indegree[ch] == 0])
    result = []

    while q:
        ch = q.popleft()
        result.append(ch)
        for neighbor in graph[ch]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                q.append(neighbor)

    return "".join(result) if len(result) == len(indegree) else ""


# 测试
print(alien_order(["wrt","wrf","er","ett","rftt"]))  # "wertf"
print(alien_order(["z","x","z"]))                     # ""  有环
print(alien_order(["z","x"]))                         # "zx"
