import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
import threading
import os
import re
import tempfile
import shutil
import time

def select_folder():
    folder_path = filedialog.askdirectory()
    if folder_path:
        input_folder_var.set(folder_path)
        update_file_info()

def select_output_file():
    file_path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 files", "*.mp4")])
    if file_path:
        output_file_var.set(file_path)

def select_audio_video():
    file_path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov")])
    if file_path:
        audio_video_var.set(file_path)
        file_name_label.config(text=f"選択された音声参照動画: {os.path.basename(file_path)}")
        # 音声参照動画フレーム数を取得して表示
        frame_count = get_frame_count(file_path)
        frame_count_label.config(text=f"音声参照動画フレーム数: {frame_count}")

def get_frame_count(file_path):
    try:
        # メタデータからフレーム数を取得
        command = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1", file_path
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return int(result.stdout.strip())
    except subprocess.CalledProcessError:
        raise ValueError("フレーム数を取得できませんでした")

def get_frame_rate(video_file):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=r_frame_rate,nb_read_packets", "-of", "csv=p=0",
             video_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True
        )

        output = result.stdout.strip().split(',')
        if len(output) != 2:
            raise ValueError("Unexpected output format from ffprobe")

        rate_str, frame_count_str = output
        if '/' in rate_str:
            num, denom = rate_str.split('/')
            frame_rate = float(num) / float(denom)
        else:
            frame_rate = float(rate_str)

        frame_count = int(frame_count_str)

        return frame_rate, frame_count

    except subprocess.CalledProcessError as e:
        messagebox.showerror("エラー", f"ffprobeの実行中にエラーが発生しました: {e.stderr}")
    except Exception as e:
        messagebox.showerror("エラー", f"フレームレートの取得中にエラーが発生しました: {str(e)}")
    
    return 30, 0  # エラー時はデフォルトで30fpsと0フレームを返す

def get_image_files_info(folder):
    image_extensions = ('.jpg', '.jpeg', '.png', '.bmp')
    image_files = [f for f in os.listdir(folder) if f.lower().endswith(image_extensions)]
    image_files.sort()  # ファイル名でソート

    if not image_files:
        return 0, None, None, [], []

    numbers = []
    for file in image_files:
        match = re.search(r'(\d+)', file)
        if match:
            numbers.append(int(match.group(1)))

    if numbers:
        first_number = min(numbers)
        last_number = max(numbers)
        all_numbers = set(range(first_number, last_number + 1))
        gaps = sorted(all_numbers - set(numbers))
    else:
        first_number = 1
        last_number = len(image_files)
        gaps = []

    return len(image_files), image_files[0], image_files[-1], numbers, gaps

def update_file_info():
    folder = input_folder_var.get()
    if folder:
        file_count, first_file, last_file, numbers, gaps = get_image_files_info(folder)
        file_count_label.config(text=f"画像ファイル数: {file_count}")
        file_range_label.config(text=f"ファイル範囲: {first_file} ～ {last_file}")
        
        gaps_text = f"欠番の総数: {len(gaps)}\n\n欠番のリスト:\n"
        for i, gap in enumerate(gaps, 1):
            gaps_text += f"{gap:06d}\n"
        
        gaps_text_area.delete(1.0, tk.END)
        gaps_text_area.insert(tk.END, gaps_text)

def extract_frame(video_file, frame_number, frame_rate, output_file):
    time = frame_number / frame_rate
    command = [
        "ffmpeg", "-i", video_file,
        "-vf", f"select='eq(n,{frame_number})'",
        "-vframes", "1", output_file
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def extract_frames(video_file, frame_numbers, frame_rate, output_folder):
    frame_select = '+'.join([f"eq(n\\,{frame})" for frame in frame_numbers])
    output_pattern = os.path.join(output_folder, '%06d.jpg').replace(os.sep, '/')
    command = [
        "ffmpeg", "-i", video_file,
        "-vf", f"select='{frame_select}'",
        "-vsync", "vfr", output_pattern
    ]
    
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    
    total_frames = len(frame_numbers)
    for i, line in enumerate(process.stdout):
        if "frame=" in line:
            progress = (i + 1) / total_frames * 100
            progress_var.set(progress)
            progress_bar.update()
            current_file_label.config(text=f"欠番生成中: {i + 1}/{total_frames} フレーム")
    
    process.wait()
    if process.returncode != 0:
        raise Exception(f"FFmpegが異常終了しました。リターンコード: {process.returncode}")

def encode_video(input_folder, output_file, encode_type, frame_rate, audio_video, gap_fill_method):
    try:
        # エンコード開始時刻を記録
        start_time = time.time()

        file_count, _, _, numbers, gaps = get_image_files_info(input_folder)
        if file_count == 0:
            raise ValueError("入力フォルダに画像ファイルが見つかりません。")

        if encode_type == "NVIDIA NVENC":
            vcodec = "h264_nvenc"
        elif encode_type == "AMD AMF":
            vcodec = "h264_amf"
        elif encode_type == "Intel":
            vcodec = "h264"
        else:  # CPU (libx264)
            vcodec = "libx264"

        generated_frames = []

        if gap_fill_method.get() == "audio_reference":
            frame_numbers = []
            for gap in gaps:
                gap_frame_path = os.path.join(input_folder, f'{gap:06d}.jpg')
                if not os.path.exists(gap_frame_path):
                    frame_numbers.append(gap - min(numbers))

            if frame_numbers:
                extract_frames(audio_video, frame_numbers, frame_rate, input_folder)
                generated_frames.extend(gaps)

                # 進捗を更新
                progress_var.set(100)
                progress_bar.update()
                current_file_label.config(text=f"欠番画像生成完了: {len(frame_numbers)}枚")

        if gap_fill_method.get() == "previous_frame":
            for gap in gaps:
                previous_frame_path = os.path.join(input_folder, f'{gap-1:06d}.jpg')
                gap_frame_path = os.path.join(input_folder, f'{gap:06d}.jpg')
                if os.path.exists(previous_frame_path):
                    # 1つ前の画像をコピーして欠番を埋める
                    shutil.copy(previous_frame_path, gap_frame_path)

        # 画像シーケンスを直接指定
        input_pattern = os.path.join(input_folder, '%06d.jpg').replace(os.sep, '/')

        command = [
            "ffmpeg", "-framerate", str(frame_rate), "-i", input_pattern,
            "-i", audio_video,
            "-c:v", vcodec, "-preset", "slow", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p", "-y", output_file
        ]

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        total_frames = max(numbers) - min(numbers) + 1  # 総フレーム数を正しく計算
        for line in process.stdout:
            if "frame=" in line:
                match = re.search(r"frame=\s*(\d+)", line)
                if match:
                    frame_number = int(match.group(1))
                    progress = (frame_number / total_frames) * 100  # 進捗を正しく計算
                    progress_var.set(progress)
                    progress_bar.update()
                    current_file_label.config(text=f"現在処理中のフレーム: {frame_number}")

            if "Error" in line or "error" in line:
                raise Exception(f"FFmpegエラー: {line.strip()}")

        process.wait()
        if process.returncode != 0:
            raise Exception(f"FFmpegが異常終了しました。リターンコード: {process.returncode}")

        # エンコード完了後にプログレスバーを100%に設定
        progress_var.set(100)
        progress_bar.update()

        # エンコード終了時刻を記録
        end_time = time.time()
        elapsed_time = end_time - start_time
        elapsed_time_str = f"エンコードにかかった時間: {elapsed_time:.2f}秒"

        if generated_frames:
            messagebox.showinfo("完了", f"動画エンコードが完了しました。\n音声参照動画から{len(generated_frames)}枚の画像を生成しました。\n{elapsed_time_str}")
        else:
            messagebox.showinfo("完了", f"動画エンコードが完了しました。\n{elapsed_time_str}")

        # エンコード完了後にボタンを再度有効化
        encode_button.config(state=tk.NORMAL)

    except Exception as e:
        # エラー発生時もボタンを再度有効化
        encode_button.config(state=tk.NORMAL)
        messagebox.showerror("エラー", f"エンコード中にエラーが発生しました: {str(e)}")

def start_encoding():
    input_folder = input_folder_var.get()
    output_file = output_file_var.get()
    audio_video = audio_video_var.get()
    encode_type = encode_type_var.get()

    if not input_folder or not output_file:
        messagebox.showerror("エラー", "入力フォルダと出力ファイルを選択してください。")
        return

    if not audio_video:
        messagebox.showerror("エラー", "音声参照動画を選択してください。")
        return

    file_count, _, _, _, _ = get_image_files_info(input_folder)
    if file_count == 0:
        messagebox.showerror("エラー", "入力フォルダに画像ファイルが見つかりません。")
        return

    frame_rate, video_frame_count = get_frame_rate(audio_video)
    
    if video_frame_count > 0 and abs(file_count - video_frame_count) > 5:
        result = messagebox.askyesno("警告", f"画像ファイル数 ({file_count}) と音声参照動画のフレーム数 ({video_frame_count}) が大きく異なります。続行しますか？")
        if not result:
            return

    # エンコード開始時にボタンを無効化
    encode_button.config(state=tk.DISABLED)
    
    # エンコードスレッドの開始
    threading.Thread(target=encode_video, args=(input_folder, output_file, encode_type, frame_rate, audio_video, gap_fill_method)).start()

# GUIのセットアップ
root = tk.Tk()
root.title("連続画像を動画に変換 & 音声ミックス")
root.geometry("800x400")

# スタイルの設定
style = ttk.Style()
style.theme_use('default')
style.configure('.', background='#e8f5e9')
style.configure('TButton', background='#4caf50', foreground='black')
style.map('TButton', background=[('active', '#45a049')])
style.configure('TLabel', background='#e8f5e9')
style.configure('TFrame', background='#e8f5e9')
style.configure('TLabelframe', background='#e8f5e9')
style.configure('TLabelframe.Label', background='#e8f5e9')

# 変数の設定
input_folder_var = tk.StringVar()
output_file_var = tk.StringVar()
audio_video_var = tk.StringVar()
encode_type_var = tk.StringVar(value="CPU")
gap_fill_method = tk.StringVar(value="audio_reference")
progress_var = tk.DoubleVar()

# メインフレームの作成
main_frame = ttk.Frame(root, padding="10")
main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# 左カラム
left_frame = ttk.Frame(main_frame, padding="5")
left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

ttk.Label(left_frame, text="入力画像フォルダ:").grid(column=0, row=0, sticky=tk.W, pady=2)
ttk.Entry(left_frame, textvariable=input_folder_var, width=40).grid(column=0, row=1, sticky=(tk.W, tk.E), pady=2)
ttk.Button(left_frame, text="参照", command=select_folder).grid(column=1, row=1, sticky=tk.W, padx=5, pady=2)

ttk.Label(left_frame, text="音声参照動画ファイル:").grid(column=0, row=2, sticky=tk.W, pady=2)
ttk.Entry(left_frame, textvariable=audio_video_var, width=40).grid(column=0, row=3, sticky=(tk.W, tk.E), pady=2)
ttk.Button(left_frame, text="参照", command=select_audio_video).grid(column=1, row=3, sticky=tk.W, padx=5, pady=2)

ttk.Label(left_frame, text="出力動画ファイル:").grid(column=0, row=4, sticky=tk.W, pady=2)
ttk.Entry(left_frame, textvariable=output_file_var, width=40).grid(column=0, row=5, sticky=(tk.W, tk.E), pady=2)
ttk.Button(left_frame, text="保存先を指定", command=select_output_file).grid(column=1, row=5, sticky=tk.W, padx=5, pady=2)

file_name_label = ttk.Label(left_frame, text="")
file_name_label.grid(column=0, row=6, columnspan=2, sticky=tk.W, pady=2)

# エンコードタイプの選択
encode_frame = ttk.LabelFrame(left_frame, text="エンコード方法", padding="5")
encode_frame.grid(column=0, row=7, columnspan=2, sticky=(tk.W, tk.E), pady=5)
ttk.Radiobutton(encode_frame, text="CPU (libx264)", variable=encode_type_var, value="CPU").grid(column=0, row=0, sticky=tk.W)
ttk.Radiobutton(encode_frame, text="NVIDIA NVENC", variable=encode_type_var, value="NVIDIA NVENC").grid(column=1, row=0, sticky=tk.W)
ttk.Radiobutton(encode_frame, text="AMD AMF", variable=encode_type_var, value="AMD AMF").grid(column=2, row=0, sticky=tk.W)
ttk.Radiobutton(encode_frame, text="Intel", variable=encode_type_var, value="Intel").grid(column=3, row=0, sticky=tk.W)

# 欠番処理方法の選択
gap_frame = ttk.LabelFrame(left_frame, text="欠番処理方法", padding="5")
gap_frame.grid(column=0, row=8, columnspan=2, sticky=(tk.W, tk.E), pady=5)
ttk.Radiobutton(gap_frame, text="音声参照動画から画像を取得", variable=gap_fill_method, value="audio_reference").grid(column=0, row=0, sticky=tk.W)
ttk.Radiobutton(gap_frame, text="抜け番の1つ前の画像を使用", variable=gap_fill_method, value="previous_frame").grid(column=0, row=1, sticky=tk.W)

# 右カラム
right_frame = ttk.Frame(main_frame, padding="5")
right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))

file_count_label = ttk.Label(right_frame, text="画像ファイル数: 0")
file_count_label.grid(column=0, row=0, sticky=tk.W, pady=2)

file_range_label = ttk.Label(right_frame, text="ファイル範囲: なし")
file_range_label.grid(column=0, row=1, sticky=tk.W, pady=2)

frame_count_label = ttk.Label(right_frame, text="音声参照動画フレーム数: なし")
frame_count_label.grid(column=0, row=2, sticky=tk.W, pady=2)

ttk.Label(right_frame, text="欠番情報:").grid(column=0, row=3, sticky=tk.W, pady=2)
gaps_text_area = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, width=30, height=8, bg='#f1f8e9')
gaps_text_area.grid(column=0, row=4, sticky=(tk.W, tk.E, tk.N, tk.S), pady=2)

ttk.Label(right_frame, text="エンコード進捗:").grid(column=0, row=5, sticky=tk.W, pady=2)
progress_bar = ttk.Progressbar(right_frame, variable=progress_var, maximum=100, style='green.Horizontal.TProgressbar')
progress_bar.grid(column=0, row=6, sticky=(tk.W, tk.E), pady=2)

current_file_label = ttk.Label(right_frame, text="現在処理中のフレーム: なし")
current_file_label.grid(column=0, row=7, sticky=tk.W, pady=2)

# エンコードボタンの作成
encode_button = ttk.Button(right_frame, text="エンコード開始", command=start_encoding)
encode_button.grid(column=0, row=8, sticky=(tk.W, tk.E), pady=5)

# カラムの重みを設定
main_frame.columnconfigure(0, weight=1)
main_frame.columnconfigure(1, weight=1)
left_frame.columnconfigure(0, weight=1)
right_frame.columnconfigure(0, weight=1)
right_frame.rowconfigure(4, weight=1)

# プログレスバーの色を設定
style.configure('green.Horizontal.TProgressbar', background='#4caf50')

# GUIの配置を調整
progress_bar.grid(column=0, row=6, sticky=(tk.W, tk.E), pady=2)  # 全幅表示

# カラムの重みを設定
right_frame.columnconfigure(0, weight=1)  # 右カラムの重みを設定

root.mainloop()