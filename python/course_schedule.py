# 思路：用拓扑排序，判断是否有环。
# 入度为 0 的入队，然后出队，然后入度为 0 的入队，然后出队，直到队列为空。
# 如果队列为空，则有环。
# 如果队列不为空，则没有环。
# 如果队列不为空，则有环。
# 如果队列不为空，则有环。

#  1.建邻接表 + 入度数组
#  2.入度为 0 的入队
#  3.依次出队，减少邻接节点入度，入度变 0 再入队
#  4.最后能上完所有课（count == numCourses）则返回 true，有环则 false 返回 false        


from typing import List
from collections import deque

def can_finish(num_courses: int, prerequisites: List[List[int]]) -> bool:
    # 建图 + 入度
    graph = [[] for _ in range(num_courses)]
    indegree = [0] * num_courses

    for course, prereq in prerequisites:
        graph[prereq].append(course)
        indegree[course] += 1

    # 入度为 0 的入队
    q = deque([i for i in range(num_courses) if indegree[i] == 0])

    count = 0
    while q:
        node = q.popleft()
        count += 1
        for neighbor in graph[node]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                q.append(neighbor)

    return count == num_courses


# 测试
print(can_finish(2, [[1, 0]]))           # True
print(can_finish(2, [[1, 0], [0, 1]]))   # False
print(can_finish(4, [[1, 0], [2, 1], [3, 2]]))  # True
