#### DeepFaceLiveで生成した画像と、元動画の音声を合成 ####

# 注意点
DeepFaceLive出力元を「合成後フレームまたは入力フレーム」にする事！！！
顔が検出できない場合は、抜け番が発生する。
一応抜け番の処理も作ったが、なるべく使わない方がいい。

エラーで止まると困るので、本エンコーダーでは自動補間を行う。

# インストール
pip install -r requirements.txt

# プロジェクトのルートにffmpeg関連ファイルを配置
https://www.ffmpeg.org/download.html

ffprobe.exe
ffmpeg.exe
ffplay.exe

