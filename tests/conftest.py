"""测试进程的部署默认包。业务代码不再写死客户包名，由环境变量提供。"""
import os

os.environ.setdefault('REPORT_PACKAGE', 'anshun_monthly')
