#include <numeric>
#include <net.h>
#include <opencv2/opencv.hpp>
#include <iostream>
#include <vector>
#include <chrono>
#include <string>
#include <thread>
#include <mutex>
#include <atomic>

struct Detection {
    int x1, y1, x2, y2;
    float conf;
    int cid;
};

// Non-Max Suppression
std::vector<int> nms(const std::vector<cv::Rect>& boxes, const std::vector<float>& scores, float threshold)
{
    std::vector<int> keep;
    if (boxes.empty()) return keep;

    std::vector<int> idx(boxes.size());
    for (size_t i = 0; i < idx.size(); i++) idx[i] = i;

    std::sort(idx.begin(), idx.end(), [&](int a, int b) { return scores[a] > scores[b]; });

    while (!idx.empty()) {
        int i = idx[0];
        keep.push_back(i);
        std::vector<int> tmp;
        for (size_t j = 1; j < idx.size(); j++) {
            float inter_x1 = std::max(boxes[i].x, boxes[idx[j]].x);
            float inter_y1 = std::max(boxes[i].y, boxes[idx[j]].y);
            float inter_x2 = std::min(boxes[i].x + boxes[i].width, boxes[idx[j]].x + boxes[idx[j]].width);
            float inter_y2 = std::min(boxes[i].y + boxes[i].height, boxes[idx[j]].y + boxes[idx[j]].height);
            float w = std::max(0.0f, inter_x2 - inter_x1);
            float h = std::max(0.0f, inter_y2 - inter_y1);
            float inter = w * h;
            float ovr = inter / (boxes[i].area() + boxes[idx[j]].area() - inter);
            if (ovr <= threshold) tmp.push_back(idx[j]);
        }
        idx = tmp;
    }
    return keep;
}

// -------------------------------------------------------
// Background thread: continuously reads MJPEG frames
// and keeps only the latest one (drops stale frames)
// -------------------------------------------------------
cv::Mat g_latest_frame;
std::mutex g_frame_mutex;
std::atomic<bool> g_running{true};
std::atomic<bool> g_has_frame{false};

void camera_thread_fn(FILE* pipe)
{
    uint8_t chunk[65536];
    std::vector<uint8_t> buf;
    buf.reserve(300000);
    bool found_start = false;

    while (g_running) {
        size_t n = fread(chunk, 1, sizeof(chunk), pipe);
        if (n == 0) { g_running = false; break; }

        for (size_t i = 0; i < n; i++) {
            buf.push_back(chunk[i]);
            size_t sz = buf.size();

            // Detect SOI (0xFF 0xD8)
            if (!found_start && sz >= 2 && buf[sz-2] == 0xFF && buf[sz-1] == 0xD8) {
                buf = {0xFF, 0xD8};
                found_start = true;
            }
            // Detect EOI (0xFF 0xD9)
            if (found_start && sz >= 2 && buf[sz-2] == 0xFF && buf[sz-1] == 0xD9) {
                cv::Mat decoded = cv::imdecode(buf, cv::IMREAD_COLOR);
                if (!decoded.empty()) {
                    std::lock_guard<std::mutex> lock(g_frame_mutex);
                    g_latest_frame = decoded;  // always overwrite with newest
                    g_has_frame = true;
                }
                buf.clear();
                found_start = false;
            }
        }
    }
}

int main()
{
    // -------------------
    // CONFIG
    // -------------------
    std::string param_file = "my_model_ncnn_model/yolo11n/model.ncnn.param";
    std::string bin_file   = "my_model_ncnn_model/yolo11n/model.ncnn.bin";
    int input_size = 640;
    float conf_thresh = 0.25f;
    float nms_thresh  = 0.45f;
    int num_classes = 8;
    std::vector<std::string> labels = {
        "Applicator white/bleu","Applicator white/gray","Applicator gray",
        "Applicator Orange /white","Applicator pink","Inhaler bleu",
        "Inhaler white","Canister"
    };

    // -------------------
    // NCNN Load
    // -------------------
    ncnn::Net net;
    net.opt.num_threads = 4;
    net.opt.use_vulkan_compute = false;
    net.opt.use_fp16_arithmetic = true;

    if (net.load_param(param_file.c_str()) != 0 || net.load_model(bin_file.c_str()) != 0) {
        std::cerr << "Failed to load model!" << std::endl;
        return -1;
    }
    std::cout << "Model loaded OK" << std::endl;

    // -------------------
    // Camera via rpicam-vid pipe (MJPEG)
    // -------------------
    FILE* pipe = popen(
        "rpicam-vid -t 0 --width 640 --height 480 --framerate 30 --codec mjpeg --inline --nopreview -o - 2>/dev/null",
        "r"
    );
    if (!pipe) {
        std::cerr << "Cannot open camera pipe" << std::endl;
        return -1;
    }
    std::cout << "Camera pipe opened OK" << std::endl;

    // Start background camera reader thread
    std::thread cam_thread(camera_thread_fn, pipe);

    // Wait for first frame
    std::cout << "Waiting for first frame..." << std::endl;
    while (!g_has_frame && g_running) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    std::cout << "Streaming started." << std::endl;

    cv::Mat frame;
    std::vector<float> fps_buffer;

    while (g_running) {
        auto t0 = std::chrono::high_resolution_clock::now();

        // Grab latest frame
        {
            std::lock_guard<std::mutex> lock(g_frame_mutex);
            if (g_latest_frame.empty()) continue;
            frame = g_latest_frame.clone();
        }

        int h0 = frame.rows, w0 = frame.cols;

        // Resize & convert to NCNN Mat
        cv::Mat img_resized;
        cv::resize(frame, img_resized, cv::Size(input_size, input_size));
        ncnn::Mat in = ncnn::Mat::from_pixels_resize(img_resized.data,
                                ncnn::Mat::PIXEL_BGR2RGB, w0, h0, input_size, input_size);
        float norm_vals[3] = { 1/255.f, 1/255.f, 1/255.f };
        in.substract_mean_normalize(nullptr, norm_vals);

        // Inference
        ncnn::Extractor ex = net.create_extractor();
        ex.input("in0", in);

        ncnn::Mat out;
        if (ex.extract("out0", out) != 0) {
            std::cerr << "Inference failed!" << std::endl;
            continue;
        }

        // Decode output
        // Shape: [num_classes+4 rows, 8400 cols] (transposed)
        int num_anchors = out.w;

        std::vector<Detection> detections;
        for (int a = 0; a < num_anchors; a++) {
            int cls_id = 0;
            float cls_score = 0.f;
            for (int c = 0; c < num_classes; c++) {
                float s = out.row(4 + c)[a];
                if (s > cls_score) {
                    cls_score = s;
                    cls_id = c;
                }
            }

            if (cls_score < conf_thresh) continue;

            float cx = out.row(0)[a];
            float cy = out.row(1)[a];
            float bw = out.row(2)[a];
            float bh = out.row(3)[a];

            float scale_x = (float)w0 / input_size;
            float scale_y = (float)h0 / input_size;

            int x1 = std::max(int((cx - bw/2) * scale_x), 0);
            int y1 = std::max(int((cy - bh/2) * scale_y), 0);
            int x2 = std::min(int((cx + bw/2) * scale_x), w0-1);
            int y2 = std::min(int((cy + bh/2) * scale_y), h0-1);

            detections.push_back({x1, y1, x2, y2, cls_score, cls_id});
        }

        // NMS
        std::vector<cv::Rect> boxes;
        std::vector<float> scores;
        for (auto& d : detections) {
            boxes.emplace_back(d.x1, d.y1, d.x2-d.x1, d.y2-d.y1);
            scores.push_back(d.conf);
        }
        std::vector<int> keep = nms(boxes, scores, nms_thresh);

        // Draw boxes
        for (int idx : keep) {
            const auto& d = detections[idx];
            cv::rectangle(frame, cv::Point(d.x1,d.y1), cv::Point(d.x2,d.y2), cv::Scalar(0,255,0), 2);
            std::string label = labels[d.cid] + " " + std::to_string((int)(d.conf*100)) + "%";
            cv::putText(frame, label, cv::Point(d.x1, std::max(d.y1-5,0)),
                        cv::FONT_HERSHEY_SIMPLEX, 0.55, cv::Scalar(0,255,0), 2);
        }

        // FPS
        auto t1 = std::chrono::high_resolution_clock::now();
        float fps = 1.f / std::chrono::duration<float>(t1-t0).count();
        fps_buffer.push_back(fps);
        if (fps_buffer.size() > 30) fps_buffer.erase(fps_buffer.begin());
        float avg_fps = std::accumulate(fps_buffer.begin(), fps_buffer.end(), 0.f) / fps_buffer.size();
        cv::putText(frame, "FPS: " + std::to_string(int(avg_fps)),
                    cv::Point(10,30), cv::FONT_HERSHEY_SIMPLEX, 0.7, cv::Scalar(0,255,255), 2);

        cv::imshow("YOLO NCNN C++", frame);
        if (cv::waitKey(1) == 27) break;
    }

    g_running = false;
    cam_thread.join();
    pclose(pipe);
    cv::destroyAllWindows();
    return 0;
}