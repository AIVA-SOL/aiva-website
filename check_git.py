import subprocess

r = subprocess.run('git --version', capture_output=True, text=True, shell=True)
print("stdout:", r.stdout)
print("stderr:", r.stderr)

r2 = subprocess.run('git -C "d:\\workbuddy智能AI\\虚拟币\\AIVA" remote -v', capture_output=True, text=True, shell=True)
print("remote:", r2.stdout)
print("remote err:", r2.stderr)

r3 = subprocess.run('git -C "d:\\workbuddy智能AI\\虚拟币\\AIVA" status', capture_output=True, text=True, shell=True)
print("status:", r3.stdout)
print("status err:", r3.stderr)
