function findOrder(numCourses: number, prerequisites: number[][]): number[] {
    const graph: number[][] = Array.from({ length: numCourses }, () => []);
    const indegree: number[] = new Array(numCourses).fill(0);

    for (const [course, prereq] of prerequisites) {
        graph[prereq].push(course);
        indegree[course]++;
    }

    const q: number[] = [];
    for (let i = 0; i < numCourses; i++) {
        if (indegree[i] === 0) q.push(i);
    }

    const result: number[] = [];
    while (q.length) {
        const node = q.shift()!;
        result.push(node);
        for (const neighbor of graph[node]) {
            indegree[neighbor]--;
            if (indegree[neighbor] === 0) q.push(neighbor);
        }
    }

    return result.length === numCourses ? result : [];
}

// 测试
console.log(findOrder(2, [[1, 0]]));                         // [0, 1]
console.log(findOrder(4, [[1, 0], [2, 0], [3, 1], [3, 2]]));
console.log(findOrder(2, [[1, 0], [0, 1]]));                 // []  有环
