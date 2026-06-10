#思路：HashMap + 双向链表，O(1) 实现。

# get：查到 key 后用 moveToHead 移到链表头部（最近使用），查不到返回 -1
# put：已存在则更新值并移到头部；不存在则插入头部，容量超出时删除链表尾部（最久未使用）
# 虚拟头尾节点（head / tail）简化边界处理

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache = {}           # key -> node
        # 双向链表：dummy head 和 dummy tail
        self.head = Node(0, 0)
        self.tail = Node(0, 0)
        self.head.next = self.tail
        self.tail.prev = self.head

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1
        node = self.cache[key]
        self._move_to_head(node)
        return node.val

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            node = self.cache[key]
            node.val = value
            self._move_to_head(node)
        else:
            if len(self.cache) >= self.capacity:
                # 删除尾部最久未使用的
                lru = self.tail.prev
                self._remove_node(lru)
                del self.cache[lru.key]
            node = Node(key, value)
            self.cache[key] = node
            self._add_to_head(node)

    def _add_to_head(self, node):
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node

    def _remove_node(self, node):
        node.prev.next = node.next
        node.next.prev = node.prev

    def _move_to_head(self, node):
        self._remove_node(node)
        self._add_to_head(node)


class Node:
    def __init__(self, key: int, val: int):
        self.key = key
        self.val = val
        self.prev = None
        self.next = None


# 测试
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
print(cache.get(1))    # 1
cache.put(3, 3)        # 淘汰 2
print(cache.get(2))    # -1
cache.put(4, 4)        # 淘汰 1
print(cache.get(1))    # -1
print(cache.get(3))    # 3
print(cache.get(4))    # 4
