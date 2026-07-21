Implement a breadth-first search (BFS) function in Python.

Create a file `bfs.py` with a function:

```python
def bfs(graph, start):
    """Return BFS visit order starting from `start`.

    graph: dict mapping node -> list of neighbor nodes.
    Returns a list of nodes in BFS order.
    """
```

Example:
```python
bfs({"A": ["B", "C"], "B": ["D"], "C": [], "D": []}, "A")
# should return ["A", "B", "C", "D"]
```

Requirements:
- Use a queue (FIFO).
- Do not revisit nodes.
- Handle the general case, not just the example above.
