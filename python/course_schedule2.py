# 和 Course Schedule I 唯一的区别：把 count 计数替换成 result 列表，最后检查长度是否等于课程总数，是则返回顺序，否则返回 []

from typing import List
from collections import deque

def find_order(num_courses: int, prerequisites: List[List[int]]) -> List[int]:
    graph = [[] for _ in range(num_courses)]
    indegree = [0] * num_courses

    for course, prereq in prerequisites:
        graph[prereq].append(course)
        indegree[course] += 1

    q = deque([i for i in range(num_courses) if indegree[i] == 0])
    result = []

    while q:
        node = q.popleft()
        result.append(node)
        for neighbor in graph[node]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                q.append(neighbor)

    return result if len(result) == num_courses else []


# 测试
print(find_order(2, [[1, 0]]))             # [0, 1]
print(find_order(4, [[1, 0], [2, 0], [3, 1], [3, 2]]))
print(find_order(2, [[1, 0], [0, 1]]))    # []  有环
