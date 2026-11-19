"""Generate enrollment_pb2.py and enrollment_pb2_grpc.py in the project root.
Run from the project root:  python gen_protos.py   (works on Windows/Mac/Linux)"""
import sys

from grpc_tools import protoc

rc = protoc.main([
    "grpc_tools.protoc",
    "-Iprotos",
    "--python_out=.",
    "--grpc_python_out=.",
    "protos/enrollment.proto",
])
if rc != 0:
    sys.exit(rc)
print("Generated enrollment_pb2.py and enrollment_pb2_grpc.py")
