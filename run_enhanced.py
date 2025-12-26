import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import threading
import os
from app import App
from file_ops import copy_with_progress, delete_path
import usb_extensions

class EnhancedApp(App):
    def __init__(self):
        super().__init__()
      
        self.title("USB实验平台")
        self.geometry("1100x850") 
        self._inject_new_features()
        self.selected_usb_mount.trace_add('write', self._update_capacity_display)

    def _inject_new_features(self):
       
        top_frame = self.winfo_children()[0]
        ttk.Button(top_frame, text="💾 导出操作日志", command=self._export_log_to_file).pack(side="right", padx=5)

        
        sel_frame = self.mount_combo.master 
        ttk.Button(sel_frame, text="⏏ 安全弹出", command=self._safe_eject).pack(side="left", padx=5)
        self.cap_var = tk.DoubleVar()
        self.cap_label = ttk.Label(sel_frame, text="容量: --", foreground="blue")
        self.cap_label.pack(side="right", padx=10)
        self.cap_bar = ttk.Progressbar(sel_frame, variable=self.cap_var, length=120)
        self.cap_bar.pack(side="right")

        
        main_paned = self.winfo_children()[1] 
        right_pane = self.nametowidget(main_paned.panes()[1]) 
        adv_frame = ttk.LabelFrame(right_pane, text="高级文件操作 (附加功能)")
        adv_frame.pack(fill="x", pady=5, padx=5, side="bottom")
        f_btns = ttk.Frame(adv_frame)
        f_btns.pack(fill="x", pady=5)
        
        ttk.Button(f_btns, text="📥 导出(U盘->电脑)", command=self._copy_from_usb).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(f_btns, text="✏️ 重命名文件", command=self._rename_file).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(f_btns, text="🗑️ 批量删除", command=self._batch_delete).pack(side="left", fill="x", expand=True, padx=2)
        self.file_tree.configure(selectmode="extended")

    def _refresh_usb_devices(self):
        for item in self.usb_tree.get_children():
            self.usb_tree.delete(item)
        try:
            devs = usb_extensions.get_enhanced_usb_list(only_storage=self.only_storage_var.get())
            for d in devs:
                self.usb_tree.insert("", "end", values=(
                    d.get("vendor_id"), d.get("product_id"),
                    d.get("manufacturer"), d.get("product"),
                    d.get("serial_number"),
                    d.get("usb_version_bcd"),
                    d.get("bus"),
                    d.get("address"),
                ))
            self._log(f"[增强版] 设备列表已更新: {len(devs)} 个")
        except Exception as e:
            self._log(f"刷新失败: {e}")

    def _update_capacity_display(self, *args):
        mount = self.selected_usb_mount.get()
        if mount and os.path.exists(mount):
            info = usb_extensions.get_disk_space(mount)
            self.cap_label.config(text=f"{info['free_gb']}G闲 / {info['total_gb']}G总")
            self.cap_var.set(info['percent'])
        else:
            self.cap_label.config(text="容量: --")
            self.cap_var.set(0)

    def _copy_from_usb(self):
        mp = self.selected_usb_mount.get()
        sel = self.file_tree.selection()
        if not sel: return messagebox.showwarning("提示", "请先选择要导出的文件")
        fname = self.file_tree.item(sel[0])['values'][0]
        src = os.path.join(mp, fname)
        dst_dir = filedialog.askdirectory(title="选择保存位置")
        if not dst_dir: return
        dst = os.path.join(dst_dir, fname)
        self.progress_text.config(text=f"正在导出: {fname}")
        self.progress_var.set(0)
        def worker():
            try:
                copy_with_progress(src, dst, on_progress=lambda p: self.after(0, lambda: self.progress_var.set(p.bytes_copied/p.total_bytes*100)))
                self.after(0, lambda: [self._log(f"导出成功: {dst}"), self.progress_text.config(text="完成")])
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("错误", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _rename_file(self):
        mp = self.selected_usb_mount.get()
        sel = self.file_tree.selection()
        if not sel: return messagebox.showwarning("提示", "请选择一个文件")
        old_name = self.file_tree.item(sel[0])['values'][0]
        new_name = simpledialog.askstring("重命名", f"请输入 {old_name} 的新名称:", parent=self)
        if new_name:
            try:
                os.rename(os.path.join(mp, old_name), os.path.join(mp, new_name))
                self._log(f"重命名成功: {old_name} -> {new_name}")
                self._refresh_file_list()
            except Exception as e:
                messagebox.showerror("重命名失败", str(e))

    def _batch_delete(self):
        mp = self.selected_usb_mount.get()
        sel = self.file_tree.selection()
        if not sel: return messagebox.showwarning("提示", "请选择至少一个文件")
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(sel)} 个项目吗？"): return
        for item in sel:
            try:
                delete_path(mp, self.file_tree.item(item)['values'][0])
            except Exception: pass
        self._log(f"批量删除结束")
        self._refresh_file_list()

    def _safe_eject(self):
        mp = self.selected_usb_mount.get()
        if not mp: return
        if messagebox.askyesno("安全弹出", f"确定弹出 {mp}?"):
            threading.Thread(target=lambda: [usb_extensions.safe_eject_drive(mp), self.after(2000, self._refresh_mounts)], daemon=True).start()
            self._log("正在尝试弹出...")

    def _export_log_to_file(self):
        text = self.log.get("1.0", "end")
        f = filedialog.asksaveasfilename(defaultextension=".txt")
        if f:
            with open(f, "w", encoding='utf-8') as file: file.write(text)
            messagebox.showinfo("完成", "日志已导出")

if __name__ == "__main__":
    app = EnhancedApp()
    app.mainloop()