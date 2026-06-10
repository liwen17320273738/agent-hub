function numIslands(grid: string[][]): number {
    const rows = grid.length;
    if (!rows) return 0;
    const cols = grid[0].length;

    let count = 0;
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];

    for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
            if (grid[r][c] === '1') {
                count++;
                // BFS 标记
                const q: number[][] = [[r, c]];
                grid[r][c] = '0';

                while (q.length) {
                    const [cr, cc] = q.shift()!;
                    for (const [dr, dc] of dirs) {
                        const nr = cr + dr;
                        const nc = cc + dc;
                        if (nr >= 0 && nr < rows && nc >= 0 && nc < cols && grid[nr][nc] === '1') {
                            grid[nr][nc] = '0';
                            q.push([nr, nc]);
                        }
                    }
                }
            }
        }
    }

    return count;
}

// 测试
const grid1 = [
    ["1","1","1","1","0"],
    ["1","1","0","1","0"],
    ["1","1","0","0","0"],
    ["0","0","0","0","0"]
];
console.log(numIslands(grid1));  // 1

const grid2 = [
    ["1","1","0","0","0"],
    ["1","1","0","0","0"],
    ["0","0","1","0","0"],
    ["0","0","0","1","1"]
];
console.log(numIslands(grid2));  // 3
