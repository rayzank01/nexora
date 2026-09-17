"""OS-level process lock: running two pollers against one database is unsupported."""
import os


class InstanceLock:
    def __init__(self,path):
        self.file=open(path,'a+b')
        self.file.seek(0)
        if os.name=='nt':
            import msvcrt
            if not self.file.read(1):
                self.file.write(b'0');self.file.flush()
            self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                self.file.close()
                raise SystemExit('Another Nexora process is using this database') from None
        else:
            import fcntl
            try:
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                self.file.close()
                raise SystemExit('Another Nexora process is using this database') from None

    def close(self):
        self.file.close()
