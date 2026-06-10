function canFinish(numCourses: number, prerequisites: number[][]): boolean {
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

    let count = 0;
    while (q.length) {
        const node = q.shift()!;
        count++;
        for (const neighbor of graph[node]) {
            indegree[neighbor]--;
            if (indegree[neighbor] === 0) q.push(neighbor);
        }
    }

    return count === numCourses;
}

// 测试
console.log(canFinish(2, [[1, 0]]));           // true
console.log(canFinish(2, [[1, 0], [0, 1]]));   // false
console.log(canFinish(4, [[1, 0], [2, 1], [3, 2]]));  // true
