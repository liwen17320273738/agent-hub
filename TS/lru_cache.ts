class ListNode {
    constructor(
        public key: number,
        public val: number,
        public prev: ListNode | null = null,
        public next: ListNode | null = null
    ) {}
}

class LRUCache {
    private capacity: number;
    private cache: Map<number, ListNode>;
    private head: ListNode;
    private tail: ListNode;

    constructor(capacity: number) {
        this.capacity = capacity;
        this.cache = new Map();
        this.head = new ListNode(0, 0);
        this.tail = new ListNode(0, 0);
        this.head.next = this.tail;
        this.tail.prev = this.head;
    }

    get(key: number): number {
        if (!this.cache.has(key)) return -1;
        const node = this.cache.get(key)!;
        this.moveToHead(node);
        return node.val;
    }

    put(key: number, value: number): void {
        if (this.cache.has(key)) {
            const node = this.cache.get(key)!;
            node.val = value;
            this.moveToHead(node);
        } else {
            if (this.cache.size >= this.capacity) {
                const lru = this.tail.prev!;
                this.removeNode(lru);
                this.cache.delete(lru.key);
            }
            const node = new ListNode(key, value);
            this.cache.set(key, node);
            this.addToHead(node);
        }
    }

    private addToHead(node: ListNode): void {
        node.prev = this.head;
        node.next = this.head.next;
        this.head.next!.prev = node;
        this.head.next = node;
    }

    private removeNode(node: ListNode): void {
        node.prev!.next = node.next;
        node.next!.prev = node.prev;
    }

    private moveToHead(node: ListNode): void {
        this.removeNode(node);
        this.addToHead(node);
    }
}

// 测试
const cache = new LRUCache(2);
cache.put(1, 1);
cache.put(2, 2);
console.log(cache.get(1));    // 1
cache.put(3, 3);              // 淘汰 2
console.log(cache.get(2));    // -1
cache.put(4, 4);              // 淘汰 1
console.log(cache.get(1));    // -1
console.log(cache.get(3));    // 3
console.log(cache.get(4));    // 4
