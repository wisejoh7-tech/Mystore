import 'dart:io' show Platform;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Drop Down',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepPurple,
          brightness: Brightness.light,
          primary: const Color(0xFF673AB7),
        ),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: Colors.deepPurple,
      ),
      home: const WebViewPage(),
    );
  }
}

class WebViewPage extends StatefulWidget {
  const WebViewPage({super.key});

  @override
  State<WebViewPage> createState() => _WebViewPageState();
}

class _WebViewPageState extends State<WebViewPage> {
  late final WebViewController _controller;
  bool _isLoading = true;
  double _progress = 0;
  bool _hasError = false;
  static const bool _isLocal = false;

  @override
  void initState() {
    super.initState();

    String initialUrl = _isLocal
        ? (!kIsWeb && Platform.isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000')
        : 'https://drop-web.onrender.com';

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.white)
      ..setUserAgent(
          "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1")
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (int progress) {
            setState(() {
              _progress = progress / 100.0;
            });
          },
          onPageStarted: (String url) => setState(() => _isLoading = true),
          onPageFinished: (String url) => setState(() => _isLoading = false),
          onWebResourceError: (WebResourceError error) {
            debugPrint("Web error: ${error.description}");
            if (error.isForMainFrame ?? true) {
              setState(() => _hasError = true);
            }
          },
          onNavigationRequest: (NavigationRequest request) {
            if (request.url.startsWith('https://www.youtube.com/')) {
              return NavigationDecision.prevent;
            }
            return NavigationDecision.navigate;
          },
        ),
      )
      ..loadRequest(Uri.parse(initialUrl));
  }

  Future<void> _refresh() async {
    setState(() {
      _hasError = false;
    });
    await _controller.reload();
  }

  @override
  Widget build(BuildContext context) {
    bool isMobile = false;
    if (!kIsWeb) {
      try {
        isMobile = Platform.isAndroid || Platform.isIOS;
      } catch (_) {}
    }

    if (!isMobile) {
      // Windows / Linux / macOS / Web placeholder with better UI
      return Scaffold(
        appBar: AppBar(
          title: const Text('Drop Down Desktop'),
          backgroundColor: Colors.deepPurple,
          foregroundColor: Colors.white,
        ),
        body: Center(
          child: Container(
            constraints: const BoxConstraints(maxWidth: 400),
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.shop_two_outlined, size: 80, color: Colors.deepPurple),
                const SizedBox(height: 24),
                Text(
                  "Drop Down",
                  style: Theme.of(context).textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 12),
                const Text(
                  "This is the desktop version of the Drop Down Store App.",
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 16, color: Colors.grey),
                ),
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: () async {
                      final url = Uri.parse('https://drop-web.onrender.com');
                      if (await canLaunchUrl(url)) {
                        await launchUrl(url, mode: LaunchMode.externalApplication);
                      }
                    },
                    icon: const Icon(Icons.open_in_browser),
                    label: const Text("LAUNCH STORE IN BROWSER"),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      backgroundColor: Colors.deepPurple,
                      foregroundColor: Colors.white,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                const Text("Note: Native WebView for Windows coming soon.",
                    style: TextStyle(fontSize: 12, color: Colors.grey))
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Drop Down'),
        centerTitle: true,
        backgroundColor: Colors.deepPurple,
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: _hasError
          ? Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.wifi_off, size: 60, color: Colors.grey),
                  const SizedBox(height: 16),
                  const Text("Unable to connect to the store."),
                  const SizedBox(height: 20),
                  ElevatedButton(onPressed: _refresh, child: const Text("Retry"))
                ],
              ),
            )
          : Column(
              children: [
                if (_isLoading) LinearProgressIndicator(value: _progress, color: Colors.orange),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _refresh,
                    child: WebViewWidget(controller: _controller),
                  ),
                ),
              ],
            ),
      bottomNavigationBar: isMobile
          ? NavigationBar(
              destinations: const [
                NavigationDestination(icon: Icon(Icons.home), label: "Home"),
                NavigationDestination(icon: Icon(Icons.shopping_cart), label: "Cart"),
                NavigationDestination(icon: Icon(Icons.person), label: "Profile"),
              ],
              onDestinationSelected: (idx) {
                String base = _isLocal
                    ? (!kIsWeb && Platform.isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000')
                    : 'https://drop-web.onrender.com';
                if (idx == 0) _controller.loadRequest(Uri.parse(base));
                if (idx == 1) _controller.loadRequest(Uri.parse('$base/cart/'));
                if (idx == 2) _controller.loadRequest(Uri.parse('$base/dashboard/'));
              },
            )
          : null,
    );
  }
}
