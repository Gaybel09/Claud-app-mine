class AdView {
  const AdView({required this.id, required this.status});

  final int id;
  final String status;

  factory AdView.fromJson(Map<String, dynamic> json) {
    return AdView(id: json['id'] as int, status: json['status'] as String);
  }
}
