
"""
Chrome分身启动器 - PyQt5版本
功能：随机启动Chrome分身、指定范围启动、指定范围关闭、关闭所有、在已打开分身中打开网址
作者：Claude AI
"""

import sys
import os
import random
import subprocess
import time
import re
import psutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                           QLabel, QLineEdit, QPushButton, QGroupBox, QProgressBar,
                           QMessageBox, QFrame, QStatusBar, QFileDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtCore import QSettings


class BackgroundWorker(QThread):
    """后台工作线程，用于处理耗时操作，避免UI卡顿"""
    update_status = pyqtSignal(str, str)  # 状态更新信号：消息，颜色
    update_progress = pyqtSignal(int)  # 进度更新信号
    finished = pyqtSignal(str, str, list)  # 完成信号：消息，颜色，处理的编号列表

    def __init__(self, profiles_data, folder_path, delay_time, mode="launch", url=None):
        """初始化后台工作线程
        
        Args:
            profiles_data: 数据列表。
                           对于 "launch" 和 "close" 模式, 这是要处理的编号列表 [num1, num2, ...]。
                           对于 "open_url" 模式, 这是 (分身编号, 用户数据目录路径, chrome.exe路径) 元组的列表 [(num, path, exe_path), ...]。
            folder_path: 快捷方式文件夹路径 (主要用于 "launch" 模式)。对于 "open_url" 和 "close" 模式可以为 None。
            delay_time: 操作间延迟时间（秒）
            mode: 操作模式："launch"、"close"或"open_url"
            url: 要打开的URL（仅在mode为"open_url"时使用）
        """
        super().__init__()
        self.profiles_data = profiles_data
        self.folder_path = folder_path # folder_path 对于 open_url 模式将是 None
        self.delay_time = delay_time
        self.mode = mode
        self.url = url
        # self.chrome_exe_path 不再需要作为全局变量，因为 open_url 模式会自带 exe 路径

    def _initialize_chrome_exe_path(self):
        """尝试自动检测chrome.exe的路径 (主要用于 launch 模式，如果未在主界面指定)
           对于 open_url 模式，将使用 profiles_data 中提供的特定 exe_path。
        """
        # 这个方法现在主要服务于 launch 模式，如果 ChromeLauncher 没有传递一个有效的 chrome_exe_path
        # 但目前我们的 launch 模式直接使用快捷方式，所以这个方法可能不太会被直接依赖。
        # 保留它以防未来有不通过快捷方式的启动模式需要全局 chrome.exe
        
        # settings = QSettings("ChromeLauncher", "Settings")
        # configured_chrome_path = settings.value("chrome_exe_path", None)
        # if configured_chrome_path and os.path.exists(configured_chrome_path):
        #     return configured_chrome_path # 返回路径而不是设置实例变量

        possible_paths = [
            r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            os.path.expanduser(r"~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe")
        ]
        for path in possible_paths:
            if os.path.exists(path):
                # settings.setValue("chrome_exe_path", path) # 可选：保存首次检测到的路径
                return path
        
        QMessageBox.critical(None, "错误", "未能自动检测到chrome.exe，请考虑在程序设置中手动指定Chrome路径！")
        return None

    def run(self):
        """根据模式执行相应操作"""
        if self.mode == "launch":
            self.launch_browsers()
        elif self.mode == "close":
            self.close_browsers() 
        elif self.mode == "open_url":
            # 对于 open_url 模式，每个条目已包含 chrome.exe 路径，不需要全局初始化
            self.open_url_in_browsers()

    def launch_browsers(self):
        """启动Chrome分身 (self.profiles_data 是编号列表)"""
        success_count = 0
        successful_numbers = []
        
        if not self.profiles_data: # 检查列表是否为空
            self.finished.emit("没有选择任何分身进行启动", "orange", [])
            return
            
        total_steps = len(self.profiles_data)
        
        for i, n in enumerate(self.profiles_data): # self.profiles_data 是编号列表
            progress = int((i + 1) / total_steps * 100)
            self.update_progress.emit(progress)
            
            if not self.folder_path: # 启动模式必须有快捷方式文件夹路径
                 self.update_status.emit(f"错误: 未提供快捷方式文件夹路径，无法启动分身 {n}", "red")
                 continue
            shortcut_path = os.path.join(self.folder_path, f"{n}.lnk")
            try:
                if os.path.exists(shortcut_path):
                    subprocess.Popen(["cmd", "/c", "start", "", shortcut_path], shell=True)
                    success_count += 1
                    successful_numbers.append(n)
                    status_text = f"正在启动: {n}"
                    self.update_status.emit(status_text, "blue")
                    time.sleep(float(self.delay_time))
                else:
                    self.update_status.emit(f"警告: 找不到快捷方式 {n}.lnk", "orange")
            except Exception as e:
                self.update_status.emit(f"警告: 启动 {n} 失败: {str(e)}", "red")
        
        if success_count > 0:
            status_text = f"成功启动{success_count}个Chrome浏览器!\n已启动编号: {', '.join(map(str, successful_numbers))}"
            self.finished.emit(status_text, "green", successful_numbers)
        else:
            self.finished.emit("错误: 没有成功启动任何浏览器 (或未提供快捷方式路径)", "red", [])

    def close_browsers(self):
        """关闭指定范围的Chrome分身 (self.profiles_data 是编号列表)"""
        closed_count = 0
        closed_numbers_set = set() # 使用集合避免重复
        
        chrome_processes = []
        for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline'], ad_value=None):
            try:
                # 确保 proc.info['name'] 和 proc.info['cmdline'] 都不是 None
                if proc.info['name'] and 'chrome.exe' in proc.info['name'].lower() and proc.info['cmdline']:
                    chrome_processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError): # 添加TypeError以防info字段为None
                continue
        
        if not self.profiles_data: # 检查列表是否为空
            self.finished.emit("没有选择任何分身进行关闭", "orange", [])
            return
            
        total_steps = len(self.profiles_data)

        for i, n in enumerate(self.profiles_data): # self.profiles_data 是编号列表
            progress = int((i + 1) / total_steps * 100)
            self.update_progress.emit(progress)
            
            # 当前关闭逻辑依赖于命令行参数中包含 "chrome<N>" 的模式。
            # 这部分可以进一步优化为使用精确的 user_data_dir (如果能从某处获取映射关系)。
            # assumed_data_dir_fragment 用来在命令行参数中寻找与分身编号相关的部分。
            assumed_data_dir_fragment_pattern = re.compile(fr"chrome{n}(?:[\\/\"']|$)", re.IGNORECASE)
            
            terminated_this_iter = False
            for proc in list(chrome_processes): # Iterate over a copy of the list
                try:
                    # 确保 cmdline 不是 None
                    if proc.info['cmdline'] is None:
                        continue
                    cmd_line_str = " ".join(proc.info['cmdline'])
                    # 使用更精确的正则匹配 --user-data-dir=\"...\\chromeN...\" 或 --user-data-dir=...\\chromeN...
                    user_data_dir_arg_match = re.search(r"--user-data-dir=(?:\"([^\"]*)\"|([^ ]+(?: [^ ]+)*?(?=(?: --|$))))", cmd_line_str)
                    if user_data_dir_arg_match:
                        user_data_path_from_cmd = user_data_dir_arg_match.group(1) or user_data_dir_arg_match.group(2)
                        if user_data_path_from_cmd and assumed_data_dir_fragment_pattern.search(user_data_path_from_cmd):
                            proc.terminate()
                            try:
                                proc.wait(timeout=3) # 增加超时时间到3秒
                            except psutil.TimeoutExpired:
                                proc.kill() # 强制杀死如果超时
                            closed_numbers_set.add(n)
                            terminated_this_iter = True
                            chrome_processes.remove(proc) # 从列表中移除，避免重复处理
                            status_text = f"已尝试关闭分身: {n}"
                            self.update_status.emit(status_text, "blue")
                            break # 假设一个编号对应一个主要用户数据目录实例
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 如果进程已经消失或无权访问，则从列表中移除
                    if proc in chrome_processes:
                         chrome_processes.remove(proc)
                    continue
                except Exception: # 其他潜在错误
                    if proc in chrome_processes:
                         chrome_processes.remove(proc)
                    continue
            
            # 如果通过 psutil 终止成功，可以尝试 taskkill 作为补充，但需小心误杀
            if terminated_this_iter:
                try:
                    # taskkill 基于窗口标题的关闭非常依赖窗口标题的命名规则
                    # 例如，如果窗口标题包含 "Profile N" 或 "chromeN"
                    # subprocess.run(f'taskkill /F /FI "IMAGENAME eq chrome.exe" /FI "WINDOWTITLE eq *chrome{n}*"', 
                    #               shell=True, check=False, capture_output=True, timeout=1)
                    pass # 暂时禁用taskkill，因为它可能不够精确，依赖psutil的终止
                except Exception:
                    pass 

            time.sleep(float(self.delay_time) / 4 if self.delay_time else 0.02) # 减少延迟

        closed_list = sorted(list(closed_numbers_set))
        if closed_list:
            status_text = f"成功关闭 {len(closed_list)} 个指定Chrome分身窗口!\n已关闭编号: {', '.join(map(str, closed_list))}"
            self.finished.emit(status_text, "green", closed_list)
        else:
            self.finished.emit("在指定范围内没有找到或未能关闭活动的Chrome分身窗口", "orange", [])


    def open_url_in_browsers(self):
        """在指定的Chrome分身中打开URL (self.profiles_data 是 (用户数据目录路径, chrome_exe路径) 元组的列表)"""
        success_count = 0
        successful_instances_info = [] # 用于记录成功操作的实例信息 (udd)

        if not self.profiles_data: # 检查列表是否为空
            self.finished.emit("没有已运行的Chrome实例来打开网址", "orange", [])
            return
            
        total_steps = len(self.profiles_data)

        for i, profile_entry in enumerate(self.profiles_data):
            progress = int((i + 1) / total_steps * 100)
            self.update_progress.emit(progress)
            
            # 解包 profile_entry - 新格式: (user_data_dir, specific_chrome_exe_path)
            if len(profile_entry) == 2:
                user_data_dir, specific_chrome_exe_path = profile_entry
            else:
                self.update_status.emit(f"警告: profiles_data 条目格式不正确，跳过。数据: {profile_entry}", "red")
                continue

            try:
                if not specific_chrome_exe_path or not os.path.exists(specific_chrome_exe_path):
                    self.update_status.emit(f"警告: Chrome.exe 路径无效或未找到: {specific_chrome_exe_path} (UDD: {os.path.basename(user_data_dir)})", "red")
                    continue

                if not isinstance(user_data_dir, str) or not os.path.isdir(user_data_dir):
                     # 对于"在已运行分身中打开"，user_data_dir 应该已存在且为目录。
                     self.update_status.emit(f"警告: 用户数据目录路径无效或不是目录: {user_data_dir}", "red")
                     continue

                cmd = [
                    specific_chrome_exe_path, 
                    f"--user-data-dir={user_data_dir}", 
                    self.url
                ]
                subprocess.Popen(cmd)
                success_count += 1
                successful_instances_info.append(os.path.basename(user_data_dir)) # 记录 UDD 的 basename 作为标识
                status_text = f"正在实例 (UDD: ...{os.path.basename(user_data_dir)}) 中打开网址: {self.url}"
                self.update_status.emit(status_text, "blue")
                time.sleep(float(self.delay_time))
            except Exception as e:
                self.update_status.emit(f"警告: 在实例 (UDD: {os.path.basename(user_data_dir)}) 中打开网址失败: {str(e)}", "red")
        
        if success_count > 0:
            status_text = f"成功在 {success_count} 个Chrome实例中打开网址!\n实例 (UDD Basenames): {', '.join(successful_instances_info)}"
            self.finished.emit(status_text, "green", successful_instances_info)
        else:
            self.finished.emit("错误: 未能在任何指定Chrome实例中打开网址", "red", [])


class ChromeLauncher(QMainWindow):
    """Chrome分身启动器主窗口"""
    
    def __init__(self):
        """初始化主窗口"""
        super().__init__()
        
        # 设置窗口标题和大小
        self.setWindowTitle("Chrome分身启动器")
        self.setMinimumSize(600, 520) # 略微增加高度以容纳新按钮
        
        # 记录已启动的分身编号
        self.launched_numbers = set()
        self._last_operation_scope_profiles = [] # 用于记录上次批量操作的完整范围
        
        # 新增：依次启动功能的状态变量
        self.sequential_launch_range_active = False
        self.sequential_launch_active_range_str = None # 保存激活当前序列的范围字符串
        self.sequential_launch_profiles = [] # 当前序列中待启动的分身编号列表
        self.sequential_launch_current_index = 0 # 指向下一个待启动分身的索引
        self._currently_attempting_sequential_profile = None # 临时存储当前尝试启动的分身号
        
        # 初始化设置
        self.settings = QSettings("ChromeLauncher", "Settings")

        # 定义用于从命令行提取分身编号的正则表达式模式
        # 这些模式会在多个地方使用 (如 open_url_in_running, _sync_launched_numbers_with_running_processes)
        self.profile_num_patterns = [
            re.compile(r"chrome[\\/]?(\\d+)", re.IGNORECASE), # 匹配 chrome<N> 或 chrome/<N> 或 chrome\\<N>
            re.compile(r"profile[\\/]?(\\d+)", re.IGNORECASE), # 匹配 profile<N>
            # 匹配 --user-data-dir=\"...chrome<N>...\" 或 --user-data-dir=...chrome<N>...
            # 修正: 确保 \\d+ 在 python 字符串中正确表示，并且在 regex 中也是 \d+
            # 正则表达式中的 \d 需要转义为 \\d，但在 Python 原始字符串 r\"\" 中不需要额外转义
            re.compile(r"--user-data-dir(?:\\\"|'|=|\s)+.*?chrome(\\\\\\d+)", re.IGNORECASE),
            # 匹配 --profile-directory=Default 或 --profile-directory=\"Profile <N>\"
            # 对于 \"Default\", 我们通常映射到0号或特殊处理，这里主要关注 \"Profile <N>\"
            re.compile(r"--profile-directory=(?:\\\"Profile\\s+(\\\\\\d+)\\\"?|Default)", re.IGNORECASE)
        ]
        # 修正 user_data_dir 正则表达式以正确处理包含空格且未加引号的路径
        # self.user_data_dir_pattern = re.compile(r'--user-data-dir=(?P<quoted>\"([^\"]*)\")|(?P<unquoted>[^ ](?:.*?[^ ])?(?=(?: --|$)))') # 旧模式
        # self.user_data_dir_pattern = re.compile(r'--user-data-dir=(?:\"(?P<path>[^"]+)\"|(?P<path_unquoted>[^\\\\s]+(?:\\\\s+[^\\\\s]+)*?(?=\\\\s*--|\\\\s*$)))') # 错误修正前的版本
        self.user_data_dir_pattern = re.compile(r'--user-data-dir=(?:\"(?P<path>[^"]+)\"|(?P<path_unquoted>[^\s]+(?:\s+[^\s]+)*?(?=\s*--|\s*$)))') # 正确修正后的版本

        # 初始化UI
        self.init_ui()
        
        # 加载保存的设置 (包括 launched_numbers 的初始加载)
        self.load_settings()
        
        # 同步/刷新 launched_numbers 以匹配当前实际运行的Chrome分身
        self._sync_launched_numbers_with_running_processes()
        
        # 应用浅色主题样式
        self.apply_light_theme()
            
        initial_status_message = "准备就绪。"
        if self.launched_numbers:
            sorted_launched_numbers = sorted(list(self.launched_numbers))
            launched_numbers_str = ", ".join(map(str, sorted_launched_numbers))
            initial_status_message += f" 当前已通过编号识别并记录的已启动分身: {launched_numbers_str}。"
        else:
            initial_status_message += " 当前没有通过编号识别的已启动分身被记录。"
        self.set_status(initial_status_message, "blue")
        self.statusBar.showMessage(f"就绪。已记录编号分身: {len(self.launched_numbers)} 个。")
    
    def init_ui(self):
        """初始化用户界面"""
        # 设置中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # === 新增：文件夹路径设置区域 ===
        folder_group = self.create_group_box("分身路径设置", "设置Chrome分身快捷方式所在文件夹")
        folder_layout = QHBoxLayout(folder_group)
        folder_layout.setContentsMargins(15, 25, 15, 15)
        
        folder_layout.addWidget(QLabel("快捷方式目录:"))
        self.folder_path = QLineEdit()
        self.folder_path.setMinimumWidth(300)
        folder_layout.addWidget(self.folder_path)
        
        browse_button = QPushButton("浏览...")
        browse_button.clicked.connect(self.browse_folder)
        browse_button.setFixedWidth(80)
        folder_layout.addWidget(browse_button)
        
        main_layout.addWidget(folder_group)
        
        # === 顶部区域：范围和数量设置 ===
        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)
        
        # 范围设置区域
        range_group = self.create_group_box("启动范围设置", "设置Chrome分身的启动范围")
        range_layout = QVBoxLayout(range_group)
        range_layout.setContentsMargins(15, 25, 15, 15)
        
        range_input_layout = QHBoxLayout()
        range_layout.addLayout(range_input_layout)
        
        range_input_layout.addWidget(QLabel("范围从:"))
        self.start_num = QLineEdit("1")
        self.start_num.setFixedWidth(60)
        self.start_num.setFixedHeight(28)
        range_input_layout.addWidget(self.start_num)
        
        range_input_layout.addWidget(QLabel("到:"))
        self.end_num = QLineEdit("100")
        self.end_num.setFixedWidth(60)
        self.end_num.setFixedHeight(28)
        range_input_layout.addWidget(self.end_num)
        
        range_input_layout.addStretch()
        
        top_layout.addWidget(range_group)
        
        # 数量设置区域
        num_group = self.create_group_box("启动数量设置", "设置一次启动的Chrome分身数量")
        num_layout = QVBoxLayout(num_group)
        num_layout.setContentsMargins(15, 25, 15, 15)
        
        num_input_layout = QHBoxLayout()
        num_layout.addLayout(num_input_layout)
        
        num_input_layout.addWidget(QLabel("启动数量:"))
        self.num_browsers = QLineEdit("5")
        self.num_browsers.setFixedWidth(60)
        self.num_browsers.setFixedHeight(28)
        num_input_layout.addWidget(self.num_browsers)
        
        num_input_layout.addStretch()
        
        top_layout.addWidget(num_group)
        
        main_layout.addLayout(top_layout)
        
        # === 中部区域：指定范围和延迟设置 ===
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(10)
        
        # 指定范围区域
        specific_group = self.create_group_box("指定范围设置", "设置要操作的Chrome分身范围")
        specific_layout = QVBoxLayout(specific_group)
        specific_layout.setContentsMargins(15, 25, 15, 15)
        
        specific_input_layout = QHBoxLayout()
        specific_layout.addLayout(specific_input_layout)
        
        specific_input_layout.addWidget(QLabel("指定范围:"))
        self.specific_range = QLineEdit("1-10")
        self.specific_range.setFixedHeight(28)
        specific_input_layout.addWidget(self.specific_range)
        
        middle_layout.addWidget(specific_group)
        
        # 延迟设置区域
        delay_group = self.create_group_box("启动延迟设置", "设置Chrome分身启动间隔时间")
        delay_layout = QVBoxLayout(delay_group)
        delay_layout.setContentsMargins(15, 25, 15, 15)
        
        delay_input_layout = QHBoxLayout()
        delay_layout.addLayout(delay_input_layout)
        
        delay_input_layout.addWidget(QLabel("启动延迟(秒):"))
        self.delay_time = QLineEdit("0.5")
        self.delay_time.setFixedWidth(60)
        self.delay_time.setFixedHeight(28)
        delay_input_layout.addWidget(self.delay_time)
        
        delay_input_layout.addStretch()
        
        middle_layout.addWidget(delay_group)
        
        main_layout.addLayout(middle_layout)
        
        # === 网址区域 ===
        url_group = self.create_group_box("打开网址", "在已打开的Chrome分身中打开指定网址")
        url_layout = QVBoxLayout(url_group)
        url_layout.setContentsMargins(15, 25, 15, 15)
        
        url_input_layout = QHBoxLayout()
        url_layout.addLayout(url_input_layout)
        
        url_input_layout.addWidget(QLabel("网址:"))
        self.url_entry = QLineEdit("https://www.example.com")
        self.url_entry.setFixedHeight(28)
        url_input_layout.addWidget(self.url_entry)
        
        url_button = QPushButton("在已打开的分身中打开网址")
        url_button.clicked.connect(self.open_url_in_running)
        url_button.setFixedHeight(32)
        url_layout.addWidget(url_button)
        
        main_layout.addWidget(url_group)
        
        # === 按钮区域 ===
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        # 创建四个主要按钮
        self.create_button("随机启动", self.launch_random_browsers, buttons_layout)
        self.create_button("指定启动", self.launch_specific_range, buttons_layout)
        self.create_button("依次启动", self.launch_sequentially, buttons_layout)
        self.create_button("指定关闭", self.close_specific_range, buttons_layout)
        self.create_button("关闭所有", self.close_all_chrome, buttons_layout)
        
        main_layout.addLayout(buttons_layout)
        
        # === 进度条 ===
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedHeight(20)
        main_layout.addWidget(self.progress_bar)
        
        # === 状态显示 ===
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.StyledPanel)
        status_frame.setFrameShadow(QFrame.Sunken)
        status_frame.setMinimumHeight(60)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 10, 10, 10)
        
        self.status_label = QLabel("准备就绪")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        
        main_layout.addWidget(status_frame)
        
        # 创建状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("准备就绪")
    
    def create_group_box(self, title, tooltip=None):
        """创建带样式的分组框
        
        Args:
            title: 分组框标题
            tooltip: 鼠标悬停提示
            
        Returns:
            QGroupBox: 样式化的分组框
        """
        group = QGroupBox(title)
        group.setFont(QFont("Microsoft YaHei", 9, QFont.Bold))
        if tooltip:
            group.setToolTip(tooltip)
        return group
    
    def create_button(self, text, callback, layout):
        """创建带样式的按钮
        
        Args:
            text: 按钮文本
            callback: 按钮点击回调函数
            layout: 要添加按钮的布局
            
        Returns:
            QPushButton: 样式化的按钮
        """
        button = QPushButton(text)
        button.clicked.connect(callback)
        button.setFixedHeight(40)
        button.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(button)
        return button
    
    def apply_light_theme(self):
        """应用浅色主题样式"""
        # 构建样式表
        self.setStyleSheet("""
            QWidget {
                background-color: #F0F0F0; /* 整体背景改为浅灰色 */
                color: #202020; /* 文字颜色改为深灰色 */
                font-size: 10pt;
            }
            
            QMainWindow {
                background-color: #E8E8E8; /* 主窗口背景稍深一点的浅灰 */
            }
            
            QGroupBox {
                background-color: #F8F8F8; /* GroupBox 背景更浅的灰色 */
                border: 1px solid #C0C0C0; /* 边框改为浅灰色 */
                border-radius: 5px;
                margin-top: 1.5em;
                font-weight: bold;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #101010; /* 标题颜色改为深色 */
            }
            
            QLabel {
                color: #202020; /* Label 文字颜色 */
                background-color: transparent;
            }
            
            QLineEdit {
                background-color: #FFFFFF; /* 输入框背景白色 */
                color: #101010; /* 输入框文字深色 */
                border: 1px solid #B0B0B0; /* 边框浅灰色 */
                border-radius: 3px;
                padding: 4px;
                selection-background-color: #ADD8E6; /* 选中文本背景浅蓝色 */
            }
            
            QPushButton {
                background-color: #0078D7; /* 按钮背景保持蓝色 */
                color: white; /* 按钮文字白色 */
                border: 1px solid #005FA3; /* 按钮边框深一点的蓝色 */
                border-radius: 3px;
                padding: 6px 12px;
                font-weight: bold;
            }
            
            QPushButton:hover {
                background-color: #1C97EA;
            }
            
            QPushButton:pressed {
                background-color: #00569C;
            }
            
            QProgressBar {
                border: 1px solid #C0C0C0; /* 边框浅灰色 */
                border-radius: 3px;
                background-color: #E0E0E0; /* 进度条背景浅灰色 */
                text-align: center;
                color: #202020; /* 进度条文字深色 */
            }
            
            QProgressBar::chunk {
                background-color: #0078D7; /* 进度条块保持蓝色 */
                width: 10px;
                margin: 0.5px;
            }
            
            QStatusBar {
                background-color: #D8D8D8; /* 状态栏背景浅灰色 */
                color: #202020; /* 状态栏文字深色 */
            }
            
            QScrollBar:vertical {
                border: 1px solid #C0C0C0;
                background: #F0F0F0;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            
            QScrollBar::handle:vertical {
                background: #C0C0C0; /* 滚动条滑块颜色 */
                min-height: 20px;
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: 1px solid #C0C0C0;
                background: #E0E0E0;
                height: 0px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
        """)
    
    def set_status(self, message, color="white"):
        """设置状态标签的文本和颜色
        
        Args:
            message: 状态消息文本
            color: 状态颜色
        """
        self.status_label.setText(message)
        
        # 设置颜色
        if color == "green":
            self.status_label.setStyleSheet("color: #4caf50; font-size: 9pt;")
        elif color == "red":
            self.status_label.setStyleSheet("color: #f44336; font-size: 9pt;")
        elif color == "blue":
            self.status_label.setStyleSheet("color: #2196f3; font-size: 9pt;")
        elif color == "orange":
            self.status_label.setStyleSheet("color: #ff9800; font-size: 9pt;")
        else: # 默认颜色
            self.status_label.setStyleSheet("color: #202020; font-size: 9pt;") # 改为深色以适应浅色主题
    
    def launch_random_browsers(self):
        """随机启动指定数量的Chrome分身"""
        try:
            # 获取范围设置
            start = int(self.start_num.text().strip())
            end = int(self.end_num.text().strip())
            count = int(self.num_browsers.text().strip())
            
            # 获取指定的文件夹路径
            folder_path = self.folder_path.text().strip()
            
            # 确认文件夹存在
            if not os.path.exists(folder_path):
                self.set_status(f"错误: 文件夹路径 {folder_path} 不存在", "red")
                self.statusBar.showMessage(f"错误: 文件夹路径不存在")
                return
                
            # 文件夹中的可用快捷方式
            available_files = [f for f in os.listdir(folder_path) if f.endswith('.lnk')]
            available_numbers = [int(f.split('.')[0]) for f in available_files if f.split('.')[0].isdigit()]
            
            # 过滤范围内的编号
            in_range_numbers = [n for n in available_numbers if start <= n <= end]
            
            # 从已有编号中排除已启动的编号
            available_to_select_from = [n for n in in_range_numbers if n not in self.launched_numbers]
            
            # 记录本次操作的完整目标范围（去重前，有效快捷方式）
            self._last_operation_scope_profiles = list(in_range_numbers) # 应该是 in_range_numbers，代表范围内的所有有效快捷方式

            if not available_to_select_from:
                self.set_status("没有可用的分身编号，所有分身可能已经启动", "orange")
                self.statusBar.showMessage("没有可用的分身编号")
                return
            
            # 如果可用数量少于请求的数量，调整数量
            count = min(count, len(available_to_select_from))
            
            # 随机选择指定数量的编号
            selected_numbers = random.sample(available_to_select_from, count)
            selected_numbers.sort()  # 排序以便按顺序启动
            
            # 显示进度条
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            # 创建并启动工作线程
            self.worker = BackgroundWorker(selected_numbers, folder_path, self.delay_time.text())
            self.worker.update_status.connect(lambda msg, color: self.set_status(msg, color))
            self.worker.update_progress.connect(self.progress_bar.setValue)
            self.worker.finished.connect(self.on_launch_finished)
            self.worker.start()
            
        except ValueError:
            self.set_status("错误: 请输入有效的数字", "red")
        except Exception as e:
            self.set_status(f"错误: {str(e)}", "red")
            self.statusBar.showMessage(f"错误: {str(e)}")
    
    def on_launch_finished(self, status_text_from_worker, color, successful_numbers):
        """启动完成后的回调
        
        Args:
            status_text_from_worker: 来自 BackgroundWorker 的原始状态文本
            color: 状态颜色
            successful_numbers: 成功启动的编号列表
        """
        # self.set_status(status_text_from_worker, color) # 不再直接使用 worker 的完整消息作为主状态
        self.progress_bar.setVisible(False)
        
        # 更新已启动编号集合
        for num in successful_numbers:
            self.launched_numbers.add(num)
        if successful_numbers: # 只有成功启动了才保存
            self.save_settings()

        main_message = ""
        if successful_numbers:
            launched_str = ", ".join(map(str, sorted(successful_numbers)))
            if len(successful_numbers) == 1:
                main_message = f"成功启动分身 {launched_str}。"
            else:
                main_message = f"成功启动分身: {launched_str}。"
            current_color = "green"
        elif "没有选择任何分身" in status_text_from_worker: 
            main_message = status_text_from_worker
            current_color = "orange"
        else: 
            main_message = f"启动操作已处理。{status_text_from_worker.split('!')[0] if '!' in status_text_from_worker else status_text_from_worker}."
            current_color = color

        remaining_count = self._get_remaining_in_range_count(self._last_operation_scope_profiles)
        if self._last_operation_scope_profiles: 
            main_message += f" 当前操作范围内还剩 {remaining_count} 个分身未启动。"
        
        # 附加当前所有已启动分身的信息
        if self.launched_numbers:
            sorted_launched_numbers = sorted(list(self.launched_numbers))
            launched_numbers_str = ", ".join(map(str, sorted_launched_numbers))
            main_message += f" 当前已记录的已启动分身: {launched_numbers_str}。"
        else:
            main_message += " 当前没有记录到已启动的分身。"
            
        self.statusBar.showMessage(main_message.split('.')[0] + f". 已记录启动: {len(self.launched_numbers)}个.") 
        self.set_status(main_message, current_color) 
        self._last_operation_scope_profiles = [] # 清理

    def launch_specific_range(self):
        """启动指定范围的Chrome分身"""
        try:
            range_text = self.specific_range.text().strip()
            if '-' not in range_text:
                self.set_status("错误: 请使用正确的格式 (例如: 1-10)", "red")
                return
                
            start, end = map(int, range_text.split('-'))
            
            # 获取指定的文件夹路径
            folder_path = self.folder_path.text().strip()
            
            # 确认文件夹存在
            if not os.path.exists(folder_path):
                self.set_status(f"错误: 文件夹路径 {folder_path} 不存在", "red")
                self.statusBar.showMessage(f"错误: 文件夹路径不存在")
                return
            
            # 动态获取文件夹中的快捷方式数量
            available_files = [f for f in os.listdir(folder_path) if f.endswith('.lnk')]
            available_numbers = set()
            for f in available_files:
                name = f.split('.')[0]
                if name.isdigit():
                    available_numbers.add(int(name))
            
            # 输入验证
            if not available_numbers:
                self.set_status("错误: 文件夹中没有可用的快捷方式", "red")
                return
            
            # 检查范围是否有效
            if start < 1 or end < 1:
                self.set_status("错误: 范围必须为正整数", "red")
                return
            if start > end:
                self.set_status("错误: 起始值不能大于结束值", "red")
                return
            
            # 获取要打开的编号列表（但仅限于文件夹中存在的快捷方式）
            numbers_in_specified_range = [n for n in range(start, end + 1) if n in available_numbers]
            
            self._last_operation_scope_profiles = list(numbers_in_specified_range)

            if not numbers_in_specified_range:
                self.set_status(f"错误: 指定范围内 {range_text} 没有找到有效的快捷方式", "red")
                self._last_operation_scope_profiles = [] # 清理以防误报
                return
            
            # 从 identified numbers_in_specified_range 中选出真正要启动的 (那些尚未在 self.launched_numbers 中的)
            numbers_to_launch = [n for n in numbers_in_specified_range if n not in self.launched_numbers]

            if not numbers_to_launch:
                self.set_status(f"指定范围 {range_text} 内的分身均已启动。还剩 0 个未启动。", "orange")
                self.statusBar.showMessage("范围内均已启动")
                self._last_operation_scope_profiles = [] # 清理
                return

            # 更新状态
            self.set_status(f"正在启动Chrome分身 (范围: {start}-{end})...", "blue")
            self.statusBar.showMessage(f"正在启动Chrome分身，范围: {start}-{end}")
            
            # 显示进度条
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            # 创建并启动工作线程
            self.worker = BackgroundWorker(numbers_to_launch, folder_path, self.delay_time.text())
            self.worker.update_status.connect(lambda msg, color: self.set_status(msg, color))
            self.worker.update_progress.connect(self.progress_bar.setValue)
            self.worker.finished.connect(self.on_launch_finished)
            self.worker.start()
                
        except ValueError:
            self.set_status("错误: 请使用正确的格式 (例如: 1-10)", "red")
            self.statusBar.showMessage("错误: 请使用正确的格式 (例如: 1-10)")
        except Exception as e:
            self.set_status(f"错误: {str(e)}", "red")
            self.statusBar.showMessage(f"错误: {str(e)}")
    
    def close_all_chrome(self):
        """关闭所有Chrome窗口"""
        try:
            reply = QMessageBox.question(self, '确认操作', 
                                      '确定要关闭所有Chrome窗口吗?',
                                      QMessageBox.Yes | QMessageBox.No, 
                                      QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                # 尝试先进行优雅关闭，去掉 /F 参数
                os.system('taskkill /IM chrome.exe')
                # 可以选择性地在这里加一个短暂的 sleep，给进程响应时间，例如 time.sleep(3)
                self.set_status("已发送关闭所有Chrome窗口的请求", "green")
                self.statusBar.showMessage("已发送关闭所有Chrome窗口的请求")
                # 清空已启动编号集合
                self.launched_numbers.clear()
                self.save_settings() # 保存清空后的状态
                
        except Exception as e:
            self.set_status(f"关闭Chrome失败: {str(e)}", "red")
            self.statusBar.showMessage(f"关闭Chrome失败: {str(e)}")
    
    def close_specific_range(self):
        """关闭指定范围的Chrome分身"""
        try:
            range_text = self.specific_range.text().strip()
            if '-' not in range_text:
                self.set_status("错误: 请使用正确的格式 (例如: 1-10)", "red")
                return
                
            start, end = map(int, range_text.split('-'))
            
            # 获取指定的文件夹路径
            folder_path = self.folder_path.text().strip()
            
            # 确认文件夹存在
            if not os.path.exists(folder_path):
                self.set_status(f"错误: 文件夹路径 {folder_path} 不存在", "red")
                self.statusBar.showMessage(f"错误: 文件夹路径不存在")
                return
            
            # 动态获取文件夹中的快捷方式数量
            available_files = [f for f in os.listdir(folder_path) if f.endswith('.lnk')]
            available_numbers = set()
            for f in available_files:
                name = f.split('.')[0]
                if name.isdigit():
                    available_numbers.add(int(name))
            
            # 输入验证
            if not available_numbers:
                self.set_status("错误: 文件夹中没有可用的快捷方式", "red")
                return
            
            # 检查范围是否有效
            if start < 1 or end < 1:
                self.set_status("错误: 范围必须为正整数", "red")
                return
            if start > end:
                self.set_status("错误: 起始值不能大于结束值", "red")
                return
            
            # 获取要关闭的编号列表
            numbers = list(range(start, end + 1))
            
            # 更新状态
            self.set_status(f"正在关闭Chrome分身 (范围: {start}-{end})...", "blue")
            self.statusBar.showMessage(f"正在关闭Chrome分身，范围: {start}-{end}")
            
            # 显示进度条
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            # 创建并启动工作线程
            self.worker = BackgroundWorker(numbers, folder_path, self.delay_time.text(), mode="close")
            self.worker.update_status.connect(lambda msg, color: self.set_status(msg, color))
            self.worker.update_progress.connect(self.progress_bar.setValue)
            self.worker.finished.connect(self.on_close_finished)
            self.worker.start()
                
        except ValueError:
            self.set_status("错误: 请使用正确的格式 (例如: 1-10)", "red")
            self.statusBar.showMessage("错误: 请使用正确的格式 (例如: 1-10)")
        except Exception as e:
            self.set_status(f"错误: {str(e)}", "red")
            self.statusBar.showMessage(f"错误: {str(e)}")
    
    def on_close_finished(self, status_text, color, closed_numbers):
        """关闭完成后的回调
        
        Args:
            status_text: 状态文本
            color: 状态颜色
            closed_numbers: 成功关闭的编号列表
        """
        # self.set_status(status_text, color) # 旧的简单设置
        self.progress_bar.setVisible(False)
        # self.statusBar.showMessage(f"完成: {status_text.split('!')[0]}!") # 旧的状态栏消息
        
        # 从已启动编号集合中移除已关闭的编号
        for num in closed_numbers:
            if num in self.launched_numbers:
                self.launched_numbers.remove(num)
        if closed_numbers: # 只有成功关闭了才保存
            self.save_settings()

        # 构建新的状态消息，并附加当前所有已启动分身的信息
        current_status_text_with_launched = status_text
        if self.launched_numbers:
            sorted_launched_numbers = sorted(list(self.launched_numbers))
            launched_numbers_str = ", ".join(map(str, sorted_launched_numbers))
            current_status_text_with_launched += f" 当前剩余已记录的已启动分身: {launched_numbers_str}。"
        else:
            current_status_text_with_launched += " 当前没有剩余记录的已启动分身。"
        
        self.set_status(current_status_text_with_launched, color)
        self.statusBar.showMessage(f"关闭操作完成。已记录启动: {len(self.launched_numbers)} 个。")
    
    def _get_remaining_in_range_count(self, profiles_in_scope_list):
        """计算指定分身编号列表中，还有多少个是未被全局启动的。"""
        if not profiles_in_scope_list:
            return 0
        # 确保 self.launched_numbers 是最新的
        return len([p for p in profiles_in_scope_list if p not in self.launched_numbers])

    def launch_sequentially(self):
        """依次启动指定范围内的Chrome分身"""
        try:
            folder_path = self.folder_path.text().strip()
            if not os.path.exists(folder_path):
                self.set_status(f"错误: 快捷方式文件夹路径 {folder_path} 不存在", "red")
                self.statusBar.showMessage("错误: 快捷方式文件夹路径不存在")
                return

            range_text = self.specific_range.text().strip()
            if '-' not in range_text:
                self.set_status("错误: 请使用正确的范围格式 (例如: 1-10)", "red")
                self.statusBar.showMessage("错误: 范围格式不正确")
                return
            
            start_s, end_s = range_text.split('-')
            start_num = int(start_s)
            end_num = int(end_s)

            if start_num < 1 or end_num < 1 or start_num > end_num:
                self.set_status("错误: 范围值无效，必须为正整数且起始不大于结束", "red")
                self.statusBar.showMessage("错误: 范围值无效")
                return
            
            # 序列初始化/重新初始化逻辑
            if not self.sequential_launch_range_active or self.sequential_launch_active_range_str != range_text:
                self.set_status(f"正在初始化依次启动序列 (范围: {range_text})...", "blue")
                available_files = [f for f in os.listdir(folder_path) if f.endswith('.lnk')]
                available_numbers_in_folder = sorted([int(f.split('.')[0]) for f in available_files if f.split('.')[0].isdigit()])
                
                self.sequential_launch_profiles = [n for n in available_numbers_in_folder if start_num <= n <= end_num]
                
                if not self.sequential_launch_profiles:
                    self.set_status(f"错误: 在指定范围 {range_text} 内没有找到有效的快捷方式。", "orange")
                    self.statusBar.showMessage("指定范围内无有效分身")
                    self.sequential_launch_range_active = False # 确保重置
                    return
                
                self.sequential_launch_current_index = 0
                self.sequential_launch_range_active = True
                self.sequential_launch_active_range_str = range_text
                
                remaining_to_initially_launch = self._get_remaining_in_range_count(self.sequential_launch_profiles)
                if remaining_to_initially_launch > 0:
                    self.set_status(f"依次启动序列已初始化 (范围: {range_text})。下一个: {self.sequential_launch_profiles[0]}。此范围还剩 {remaining_to_initially_launch} 个待启动。", "blue")
                    self.statusBar.showMessage(f"序列初始化。下一个: {self.sequential_launch_profiles[0]}. 还剩 {remaining_to_initially_launch}")
                else:
                    self.set_status(f"依次启动序列 (范围: {range_text}) 内分身均已启动或无有效分身。还剩 0 个待启动。", "orange")
                    self.statusBar.showMessage("序列中无待启动分身")
                    self.sequential_launch_range_active = False # 无可启动，则序列非激活
                    return # 避免后续逻辑出错
            
            # 执行序列启动逻辑
            if not self.sequential_launch_range_active: # 如果初始化失败或序列已被标记为非激活
                self.set_status("请先使用有效范围初始化依次启动序列。", "orange")
                self.statusBar.showMessage("序列未激活")
                return

            # 跳过已启动的分身
            while self.sequential_launch_current_index < len(self.sequential_launch_profiles) and \
                  self.sequential_launch_profiles[self.sequential_launch_current_index] in self.launched_numbers:
                skipped_profile = self.sequential_launch_profiles[self.sequential_launch_current_index]
                self.sequential_launch_current_index += 1
                remaining_after_skip = 0
                if self.sequential_launch_range_active: # 仅当序列仍激活时计算
                    # 从当前索引开始计算剩余
                    remaining_after_skip = len([p for p in self.sequential_launch_profiles[self.sequential_launch_current_index:] if p not in self.launched_numbers])
                self.set_status(f"分身 {skipped_profile} 已启动，自动跳过。还剩 {remaining_after_skip} 个待启动。", "orange")
                self.statusBar.showMessage(f"已跳过 {skipped_profile}。还剩 {remaining_after_skip}")
            
            # 检查序列是否完成
            if self.sequential_launch_current_index >= len(self.sequential_launch_profiles):
                self.set_status(f"依次启动序列 (范围: {self.sequential_launch_active_range_str}) 已全部处理完毕。还剩 0 个待启动。", "green")
                self.statusBar.showMessage("依次启动序列完成")
                self.sequential_launch_range_active = False # 重置序列
                return
            
            # 启动下一个分身
            profile_to_launch = self.sequential_launch_profiles[self.sequential_launch_current_index]
            self._currently_attempting_sequential_profile = profile_to_launch

            self.set_status(f"正在尝试依次启动分身: {profile_to_launch}...", "blue")
            self.statusBar.showMessage(f"正在启动: {profile_to_launch}")
            self.progress_bar.setValue(0) # 重置进度条以用于单次启动
            self.progress_bar.setVisible(True)

            self.worker = BackgroundWorker([profile_to_launch], folder_path, self.delay_time.text())
            self.worker.update_status.connect(lambda msg, color: self.set_status(msg, color)) # 可以简化或移除，因为主要状态由 on_sequential_launch_item_finished 控制
            self.worker.update_progress.connect(self.progress_bar.setValue)
            self.worker.finished.connect(self.on_sequential_launch_item_finished)
            self.worker.start()

        except ValueError:
            self.set_status("错误: 范围中请输入有效的数字", "red")
            self.statusBar.showMessage("错误: 范围数字无效")
            # 重置序列状态，以防部分初始化
            self.sequential_launch_range_active = False
            self.sequential_launch_active_range_str = None
            self.sequential_launch_profiles = []
            self.sequential_launch_current_index = 0
        except Exception as e:
            self.set_status(f"依次启动时发生意外错误: {str(e)}", "red")
            self.statusBar.showMessage(f"意外错误: {str(e)}")
            # 重置序列状态
            self.sequential_launch_range_active = False
            self.sequential_launch_active_range_str = None
            self.sequential_launch_profiles = []
            self.sequential_launch_current_index = 0
            import traceback
            traceback.print_exc()

    def on_sequential_launch_item_finished(self, status_text_from_worker, color_from_worker, successful_numbers_from_worker):
        """单个依次启动项完成后的回调"""
        profile_launched_attempt = self._currently_attempting_sequential_profile
        self._currently_attempting_sequential_profile = None # 清理
        self.progress_bar.setVisible(False)

        if profile_launched_attempt is None: # 不应该发生，但作为保险
            self.set_status("依次启动回调错误：未记录尝试的分身", "red")
            return

        if successful_numbers_from_worker and profile_launched_attempt in successful_numbers_from_worker:
            self.launched_numbers.add(profile_launched_attempt)
            self.sequential_launch_current_index += 1
            self.save_settings() # 保存状态
            
            remaining_in_seq = 0
            next_profile_to_show = None
            if self.sequential_launch_range_active: # 仅当序列仍认为自己是激活状态时计算
                # 计算从当前 self.sequential_launch_current_index 开始的剩余未启动项
                temp_remaining_profiles = []
                for i in range(self.sequential_launch_current_index, len(self.sequential_launch_profiles)):
                    p_num = self.sequential_launch_profiles[i]
                    if p_num not in self.launched_numbers:
                        temp_remaining_profiles.append(p_num)
                remaining_in_seq = len(temp_remaining_profiles)
                if temp_remaining_profiles:
                    next_profile_to_show = temp_remaining_profiles[0]
            
            status_msg_on_success = f"分身 {profile_launched_attempt} 已成功启动。"
            if self.sequential_launch_range_active and remaining_in_seq > 0 and next_profile_to_show is not None:
                status_msg_on_success += f" 下一个: {next_profile_to_show}。序列中还剩 {remaining_in_seq} 个待启动。"
                self.statusBar.showMessage(f"成功 {profile_launched_attempt}。下一个: {next_profile_to_show}。还剩 {remaining_in_seq}")
            elif self.sequential_launch_range_active and remaining_in_seq == 0: # 刚启动的是最后一个
                status_msg_on_success += f" 序列 (范围: {self.sequential_launch_active_range_str}) 已全部处理完毕。还剩 0 个待启动。"
                self.statusBar.showMessage(f"成功 {profile_launched_attempt}。序列完成")
                self.sequential_launch_range_active = False # 重置序列
            else: # 序列已完成或不再激活 (例如在 launch_sequentially 中被重置)
                status_msg_on_success += f" 序列 (范围: {self.sequential_launch_active_range_str}) 已全部处理完毕。还剩 0 个待启动。"
                self.statusBar.showMessage(f"成功 {profile_launched_attempt}。序列完成")
                self.sequential_launch_range_active = False # 确保重置
            
            # 附加总的已启动列表
            if self.launched_numbers:
                sorted_launched_numbers_total = sorted(list(self.launched_numbers))
                launched_numbers_total_str = ", ".join(map(str, sorted_launched_numbers_total))
                status_msg_on_success += f" (总已启动编号: {launched_numbers_total_str})."
            self.set_status(status_msg_on_success, "green")

        else: # 启动失败
            # self.set_status(f"分身 {profile_launched_attempt} 启动失败。错误: {status_text_from_worker}", "red") # 旧消息
            # self.statusBar.showMessage(f"分身 {profile_launched_attempt} 启动失败") # 旧状态栏
            
            failure_message = f"分身 {profile_launched_attempt} 启动失败。错误: {status_text_from_worker}."
            remaining_on_fail = 0
            if self.sequential_launch_range_active:
                 # 从当前索引（未改变）开始计算
                 temp_remaining_profiles_on_fail = []
                 for i in range(self.sequential_launch_current_index, len(self.sequential_launch_profiles)):
                    p_num = self.sequential_launch_profiles[i]
                    if p_num not in self.launched_numbers:
                        temp_remaining_profiles_on_fail.append(p_num)
                 remaining_on_fail = len(temp_remaining_profiles_on_fail)
            
            if self.sequential_launch_range_active and remaining_on_fail > 0:
                failure_message += f" 序列中还剩 {remaining_on_fail} 个待启动 (包括当前失败的)。"
                self.statusBar.showMessage(f"失败 {profile_launched_attempt}。序列还剩 {remaining_on_fail}。")
            elif self.sequential_launch_range_active: # 意味着 remaining_on_fail is 0, but sequence was active
                 failure_message += " 序列中可能没有更多可尝试的未启动项了。"
                 self.statusBar.showMessage(f"失败 {profile_launched_attempt}。序列可能已无后续。")
            else: # sequence not active
                self.statusBar.showMessage(f"分身 {profile_launched_attempt} 启动失败。")
            
            # 附加总的已启动列表
            if self.launched_numbers:
                sorted_launched_numbers_total_fail = sorted(list(self.launched_numbers))
                launched_numbers_total_fail_str = ", ".join(map(str, sorted_launched_numbers_total_fail))
                failure_message += f" (当前总已启动编号: {launched_numbers_total_fail_str})."
            else:
                failure_message += " (当前无已记录启动编号)."
            self.set_status(failure_message, "red")

    def open_url_in_running(self):
        """在所有已打开的Chrome实例中打开网址 (新思路：直接操作窗口/进程，不再依赖分身编号)"""
        try:
            url = self.url_entry.text().strip()
            if not url:
                self.set_status("错误: 请输入有效的网址", "red")
                self.statusBar.showMessage("错误: 网址不能为空")
                return
                
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            # target_profiles_info 将存储 (用户数据目录路径, 该实例的chrome.exe路径) 元组
            # 使用字典以 user_data_dir 作为键来自动去重，值为 chrome_exe_path
            unique_running_instances = {}
            
            user_data_dir_pattern = self.user_data_dir_pattern # 使用在 __init__ 中定义的模式
            processed_pids = set()

            print("DEBUG_OPEN_URL_NEW: Starting to scan running Chrome processes...")

            for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline', 'exe'], ad_value=None):
                try:
                    if proc.pid in processed_pids:
                        continue
                    
                    proc_info = proc.info
                    if not proc_info or \
                       not proc_info.get('name') or \
                       'chrome.exe' not in proc_info['name'].lower() or \
                       not proc_info.get('cmdline') or \
                       not proc_info.get('exe'):
                        continue
                    
                    cmd_line_list = proc_info['cmdline']
                    cmd_line_str = " ".join(cmd_line_list)
                    proc_exe_path = proc_info['exe']

                    print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, EXE='{proc_exe_path}', CMD_LINE='{cmd_line_str}'")

                    actual_user_data_dir = None
                    match_ud_dir = user_data_dir_pattern.search(cmd_line_str)

                    if match_ud_dir:
                        # 提取路径，优先尝试带引号的路径组，然后尝试不带引号的路径组
                        raw_udd = match_ud_dir.group('path') or match_ud_dir.group('path_unquoted')
                        if raw_udd:
                            actual_user_data_dir = os.path.normpath(raw_udd.strip())
                            print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, Extracted UDD: '{actual_user_data_dir}'")
                            
                            # 确保提取到的 user_data_dir 是一个有效的目录，并且 proc_exe_path 存在
                            if actual_user_data_dir and os.path.isdir(actual_user_data_dir) and \
                               proc_exe_path and os.path.exists(proc_exe_path):
                                # 以 user_data_dir 为键，如果已存在，则不更新（保留第一个遇到的exe_path）
                                # 或者可以更新为最新的，或者基于某种逻辑选择，这里简单保留第一个
                                if actual_user_data_dir not in unique_running_instances:
                                    unique_running_instances[actual_user_data_dir] = proc_exe_path
                                    print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, ADDED instance: UDD='{actual_user_data_dir}', EXE='{proc_exe_path}'")
                                else:
                                    print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, Instance already recorded for UDD: '{actual_user_data_dir}'")
                            else:
                                print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, SKIPPED - Invalid UDD ('{actual_user_data_dir}', is_dir={os.path.isdir(actual_user_data_dir) if actual_user_data_dir else 'N/A'}) or EXE path ('{proc_exe_path}', exists={os.path.exists(proc_exe_path) if proc_exe_path else 'N/A'}).")
                        else:
                            print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, SKIPPED - Could not extract UDD string from regex match.")
                    else:
                        print(f"DEBUG_OPEN_URL_NEW: PID={proc.pid}, SKIPPED - user_data_dir_pattern did not match.")

                    processed_pids.add(proc.pid)

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue 
                except (TypeError, ValueError, AttributeError) as e_data_handling:
                    print(f"DEBUG_OPEN_URL_NEW_DATA_HANDLING_ERROR: PID (approx {proc.pid if proc and hasattr(proc, 'pid') else 'N/A'}): {str(e_data_handling)}")
                    continue 
                except Exception as e_general_proc:
                    print(f"DEBUG_OPEN_URL_NEW_GENERAL_ERROR: PID (approx {proc.pid if proc and hasattr(proc, 'pid') else 'N/A'}): {str(e_general_proc)}")
                    continue
            
            final_target_instances = list(unique_running_instances.items()) # 转换为 [(udd, exe_path), ...] 列表
            # Sort by UDD path for consistent ordering, though not strictly necessary for functionality
            final_target_instances.sort(key=lambda x: x[0]) 
            
            print(f"DEBUG_OPEN_URL_NEW: FINAL target instances for URL opening: {final_target_instances}")

            if not final_target_instances:
                self.set_status("没有找到正在运行的、可操作的Chrome实例", "orange")
                self.statusBar.showMessage("没有找到正在运行的Chrome实例")
                return

            self.set_status(f"准备在 {len(final_target_instances)} 个已运行Chrome实例中打开网址...", "blue")
            self.statusBar.showMessage(f"正在打开网址: {url}")
            
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            
            # BackgroundWorker 的 profiles_data 现在是 [(user_data_dir, exe_path), ...]
            self.worker = BackgroundWorker(profiles_data=final_target_instances, 
                                         folder_path=None, 
                                         delay_time=self.delay_time.text(), 
                                         mode="open_url", url=url)
            self.worker.update_status.connect(lambda msg, color: self.set_status(msg, color))
            self.worker.update_progress.connect(self.progress_bar.setValue)
            self.worker.finished.connect(self.on_open_url_finished)
            self.worker.start()
                
        except ValueError as ve:
            self.set_status(f"输入错误: {str(ve)}", "red")
            self.statusBar.showMessage(f"输入错误: {str(ve)}")
        except Exception as e_global:
            self.set_status(f"打开URL时发生全局错误: {str(e_global)}", "red")
            self.statusBar.showMessage(f"全局错误: {str(e_global)}")
            import traceback
            traceback.print_exc()
    
    def on_open_url_finished(self, status_text, color, successful_instances_info):
        """打开URL完成后的回调
        
        Args:
            status_text: 状态文本
            color: 状态颜色
            successful_instances_info: 成功打开URL的实例信息列表 (UDD basenames)
        """
        # self.set_status(status_text, color) # 旧的
        self.progress_bar.setVisible(False)
        # self.statusBar.showMessage(f"完成: {status_text.split('!')[0]}!") # 旧的
        
        # 附加当前所有已记录的"编号分身"信息，以供参考
        current_status_text_with_launched = status_text
        if self.launched_numbers:
            sorted_launched_numbers = sorted(list(self.launched_numbers))
            launched_numbers_str = ", ".join(map(str, sorted_launched_numbers))
            current_status_text_with_launched += f" (当前已记录的编号分身: {launched_numbers_str})."
        else:
            current_status_text_with_launched += " (当前没有记录到已启动的编号分身)."

        self.set_status(current_status_text_with_launched, color)
        self.statusBar.showMessage(f"{status_text.split('!')[0]}! 已记录编号分身: {len(self.launched_numbers)} 个。")
    
    def browse_folder(self):
        """打开文件夹浏览对话框选择分身快捷方式目录"""
        current_path = self.folder_path.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "选择分身快捷方式目录", 
                                                current_path)
        if folder:
            self.folder_path.setText(folder)
            # 保存设置
            self.save_settings()
            
    def save_settings(self):
        """保存用户设置"""
        self.settings.setValue("folder_path", self.folder_path.text())
        self.settings.setValue("start_num", self.start_num.text())
        self.settings.setValue("end_num", self.end_num.text())
        self.settings.setValue("launch_count", self.num_browsers.text())
        self.settings.setValue("delay_time", self.delay_time.text())
        self.settings.setValue("specific_range", self.specific_range.text())
        self.settings.setValue("url", self.url_entry.text())
        # 保存已启动的分身编号列表 (作为字符串列表)
        # QSettings 不直接支持 set, 所以转换为 list of strings
        launched_list_str = sorted([str(n) for n in self.launched_numbers])
        self.settings.setValue("launched_numbers", launched_list_str)
    
    def load_settings(self):
        """加载用户设置"""
        # 从设置中加载保存的值，如果没有则使用默认值
        folder_path = self.settings.value("folder_path", "E:\\chrome copy\\chrome")
        start_num = self.settings.value("start_num", "1")
        end_num = self.settings.value("end_num", "100")
        launch_count = self.settings.value("launch_count", "5")
        delay_time = self.settings.value("delay_time", "0.5")
        specific_range = self.settings.value("specific_range", "1-10")
        url = self.settings.value("url", "https://www.example.com")
        # 加载已启动的分身编号列表
        # 确保提供一个默认的空列表，如果键不存在
        launched_list_str = self.settings.value("launched_numbers", [])
        # 转换为整数集合
        current_launched_numbers = set()
        if isinstance(launched_list_str, list): # 确保是列表
            for item in launched_list_str:
                try:
                    current_launched_numbers.add(int(item))
                except ValueError:
                    print(f"警告: 从设置加载 launched_numbers 时，无法转换 '{item}' 为整数。")
        else: # 如果不是列表（例如，首次运行可能是None，或者旧格式）
            print(f"警告: launched_numbers 从设置中加载的不是列表类型: {type(launched_list_str)}")
            
        self.launched_numbers = current_launched_numbers

        # 设置控件的值
        self.folder_path.setText(folder_path)
        self.start_num.setText(start_num)
        self.end_num.setText(end_num)
        self.num_browsers.setText(launch_count)
        self.delay_time.setText(delay_time)
        self.specific_range.setText(specific_range)
        self.url_entry.setText(url)
        self.save_settings()
    
    def closeEvent(self, event):
        """程序关闭时的事件处理"""
        # 保存设置
        self.save_settings()
        # 接受关闭事件
        event.accept()

    def _sync_launched_numbers_with_running_processes(self):
        """
        扫描当前运行的Chrome进程，并用实际运行的分身编号更新 self.launched_numbers。
        这确保了程序状态与系统实际状态的一致性，特别是在手动关闭分身或程序异常退出后。
        """
        print("DEBUG: Synchronizing launched_numbers with running processes...")
        actually_running_profiles = set()
        try:
            user_data_dir_pattern = self.user_data_dir_pattern # 使用实例属性
            profile_num_patterns = self.profile_num_patterns   # 使用实例属性
            processed_pids_sync = set() # 避免重复处理同一进程

            for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline', 'exe'], ad_value=None):
                try:
                    # 在每次迭代开始时初始化这些变量
                    actual_user_data_dir_sync = None
                    extracted_profile_num_sync = None

                    if proc.pid in processed_pids_sync:
                        continue
                    
                    proc_info = proc.info
                    if not proc_info or \
                       not proc_info.get('name') or \
                       'chrome.exe' not in proc_info['name'].lower() or \
                       not proc_info.get('cmdline'):
                        continue
                    
                    cmd_line_list = proc_info['cmdline']
                    cmd_line_str = " ".join(cmd_line_list)
                    
                    # 尝试从 user-data-dir 路径中提取编号 (更可靠)
                    # actual_user_data_dir_sync # 已在循环顶部初始化为None
                    # extracted_profile_num_sync # 已在循环顶部初始化为None
                    match_ud_dir_sync = user_data_dir_pattern.search(cmd_line_str)
                    if match_ud_dir_sync:
                        print(f"DEBUG_SYNC_UDD_PARSE: PID={proc.pid}, user_data_dir_pattern matched. Groups: {match_ud_dir_sync.groups()}")
                        # 提取路径，优先尝试带引号的路径组，然后尝试不带引号的路径组
                        raw_udd_sync = match_ud_dir_sync.group('path') or match_ud_dir_sync.group('path_unquoted')
                        
                        if raw_udd_sync:
                            print(f"DEBUG_SYNC_UDD_PARSE: PID={proc.pid}, Raw UDD extracted: '{raw_udd_sync}', type: {type(raw_udd_sync)}")
                            # 不需要再手动去除引号，因为 (?P<path>[^"]+) 组已不包含引号
                            actual_user_data_dir_sync = os.path.normpath(raw_udd_sync.strip())
                            print(f"DEBUG_SYNC_UDD_PARSE: PID={proc.pid}, Normalized actual_user_data_dir: '{actual_user_data_dir_sync}', type: {type(actual_user_data_dir_sync)}")
                            
                            if actual_user_data_dir_sync: # Ensure actual_user_data_dir_sync is not None or empty
                                path_basename_sync = os.path.basename(actual_user_data_dir_sync)
                                match_basename_sync = re.search(r"chrome(\\\d+)", path_basename_sync, re.IGNORECASE)
                                if match_basename_sync:
                                    extracted_profile_num_sync = int(match_basename_sync.group(1))
                                else:
                                    parent_basename_sync = os.path.basename(os.path.dirname(actual_user_data_dir_sync))
                                    match_parent_basename_sync = re.search(r"chrome(\\\d+)", parent_basename_sync, re.IGNORECASE)
                                    if match_parent_basename_sync:
                                         extracted_profile_num_sync = int(match_parent_basename_sync.group(1))
                        # No explicit else here, if raw_udd_sync is None, actual_user_data_dir_sync remains None
                    # No specific error caught here for match_ud_dir_sync being None or regex failing early for user-data-dir

                    # If extracted_profile_num_sync is still None after UDD parsing, try other patterns
                    if extracted_profile_num_sync is None:
                        for p_pattern_sync in profile_num_patterns:
                            match_profile_sync = p_pattern_sync.search(cmd_line_str)
                            if match_profile_sync:
                                try:
                                    num_str_sync = match_profile_sync.group(1)
                                    if p_pattern_sync.pattern == r"--profile-directory=(?:\\\"?Profile\\s+(\\\d+)\\\"?|Default)":
                                        print(f"DEBUG_SYNC_PROFILE_DIR_MATCH: PID={proc.pid}, Pattern='{p_pattern_sync.pattern}', FullMatch='{match_profile_sync.group(0)}', Group1='{num_str_sync}', AllGroups={match_profile_sync.groups()}")
                                    if num_str_sync:
                                        extracted_profile_num_sync = int(num_str_sync)
                                        print(f"DEBUG_SYNC_PROFILE_ASSIGNED: PID={proc.pid}, extracted_profile_num_sync assigned: {extracted_profile_num_sync}")
                                        break
                                    elif "Default" in match_profile_sync.group(0) and "Profile" not in match_profile_sync.group(0) and p_pattern_sync.pattern == r"--profile-directory=(?:\\\"?Profile\\s+(\\\d+)\\\"?|Default)":
                                        print(f"DEBUG_SYNC_PROFILE_DIR_MATCH: PID={proc.pid}, Matched Default profile.")
                                        pass # Default usually not counted or handled as a numbered profile here
                                except (IndexError, ValueError, AttributeError) as e_parse_group: # Added AttributeError
                                    print(f"DEBUG_SYNC_PROFILE_DIR_MATCH_ERROR: PID={proc.pid}, Pattern='{p_pattern_sync.pattern}', Error: {e_parse_group} for match '{match_profile_sync.group(0) if match_profile_sync else 'NO MATCH'}'")
                                    continue # Error in group extraction or int conversion

                    if extracted_profile_num_sync is not None:
                        actually_running_profiles.add(extracted_profile_num_sync)
                    # No "NOT ADDED" print here in sync function, only in open_url
                    
                    processed_pids_sync.add(proc.pid)

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except (TypeError, ValueError, AttributeError) as e_data_handling_sync: # Added AttributeError here too
                    print(f"DEBUG_SYNC_DATA_HANDLING_ERROR: PID (approx {proc.pid if proc and hasattr(proc, 'pid') else 'N/A'}): {str(e_data_handling_sync)}")
                    continue
                except Exception as e_general_proc_sync:
                    print(f"DEBUG_SYNC_GENERAL_ERROR: PID (approx {proc.pid if proc and hasattr(proc, 'pid') else 'N/A'}): {str(e_general_proc_sync)}")
                    # traceback.print_exc() # Optionally re-enable for very deep debugging
                    continue
            
            self.launched_numbers = actually_running_profiles
            print(f"DEBUG: Synchronized. self.launched_numbers is now: {self.launched_numbers}")
            # 保存同步后的状态
            self.save_settings()

        except Exception as e:
            print(f"错误: 同步已运行分身状态失败: {str(e)}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle('Fusion')  # 使用Fusion风格，更现代化
        window = ChromeLauncher()
        window.setWindowIcon(QIcon("ico.ico")) # 设置应用程序图标
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "错误", f"程序启动失败: {str(e)}")
