"""
SAOM Library Examples - Run this file to see SAOM in action.
"""

from saom_lib import SAOM

# Create SAOM instance
saom = SAOM()

# 1. Chat
print("=" * 50)
print("1. CHAT")
print("=" * 50)
print(saom.chat("What is the difference between a list and a tuple in Python?"))

# 2. Write code
print("\n" + "=" * 50)
print("2. WRITE CODE")
print("=" * 50)
print(saom.write("write a function to check if a number is prime"))

# 3. Fix a bug
print("\n" + "=" * 50)
print("3. FIX BUG")
print("=" * 50)
buggy_code = """
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n)  # Bug: infinite recursion
"""
print(saom.fix_bug(buggy_code))

# 4. Understand code
print("\n" + "=" * 50)
print("4. UNDERSTAND CODE")
print("=" * 50)
mystery_code = """
def mystery(s):
    return ''.join(c for c in s if c.isupper())
"""
print(saom.understand(mystery_code))

# 5. Review code
print("\n" + "=" * 50)
print("5. REVIEW CODE")
print("=" * 50)
code_to_review = """
def get_user(id):
    users = {"1": "Alice", "2": "Bob"}
    return users[id]
"""
print(saom.review(code_to_review))

# 6. Search
print("\n" + "=" * 50)
print("6. SEARCH")
print("=" * 50)
print(saom.search("Python best practices 2025"))

# 7. Run code
print("\n" + "=" * 50)
print("7. RUN CODE")
print("=" * 50)
print(saom.run_code("print([i**2 for i in range(10)])"))

print("\n" + "=" * 50)
print("DONE - All examples completed!")
