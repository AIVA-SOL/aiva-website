import os, subprocess

aiva_path = r'd:\workbuddy智能AI\虚拟币\AIVA'
print("=== 目录内容（含隐藏）===")
for f in os.listdir(aiva_path):
    print(f)

print("\n=== .git 是否存在 ===")
git_dir = os.path.join(aiva_path, '.git')
print("存在" if os.path.exists(git_dir) else "不存在")

print("\n=== git remote -v ===")
r = subprocess.run(['git', 'remote', '-v'], cwd=aiva_path, capture_output=True, text=True)
print(r.stdout or r.stderr)

print("\n=== git status ===")
r2 = subprocess.run(['git', 'status'], cwd=aiva_path, capture_output=True, text=True)
print(r2.stdout or r2.stderr)
