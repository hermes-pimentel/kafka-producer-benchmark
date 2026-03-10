package com.example.msktest;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.clients.producer.RecordMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;

import java.io.FileWriter;
import java.io.PrintWriter;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

@Component
public class KafkaProducerRunner implements CommandLineRunner {

    private static final Logger log = LoggerFactory.getLogger(KafkaProducerRunner.class);
    private final KafkaTemplate<String, String> kafkaTemplate;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${app.topic}")
    private String topic;

    @Value("${app.message-count}")
    private int messageCount;

    @Value("${app.duration-minutes}")
    private int durationMinutes;

    @Value("${app.message-size-bytes}")
    private int messageSizeBytes;

    @Value("${app.batch-size}")
    private int batchSize;

    @Value("${app.threads}")
    private int threads;

    public KafkaProducerRunner(KafkaTemplate<String, String> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    record SendRecord(int threadId, int seq, long latencyMs, int partition, long offset, long timestamp) {}

    @Override
    public void run(String... args) throws Exception {
        ensureTopicExists();

        boolean timeMode = messageCount <= 0;
        String mode = timeMode ? durationMinutes + " min" : messageCount + " msgs";
        log.info("Starting producer: mode={}, batchSize={}, threads={}, topic={}", mode, batchSize, threads, topic);

        List<SendRecord> allRecords = new ArrayList<>();
        long totalStart = System.currentTimeMillis();
        long deadline = timeMode ? totalStart + (long) durationMinutes * 60_000 : Long.MAX_VALUE;

        int perThreadCount = messageCount > 0 ? messageCount : 0;

        ExecutorService executor = Executors.newFixedThreadPool(threads);
        List<java.util.concurrent.Future<List<SendRecord>>> futures = new ArrayList<>();

        for (int t = 0; t < threads; t++) {
            final int threadId = t;
            futures.add(executor.submit(() -> produceMessages(threadId, perThreadCount, deadline, timeMode)));
        }

        int totalSent = 0;
        for (var f : futures) {
            List<SendRecord> threadRecords = f.get();
            totalSent += threadRecords.size();
            allRecords.addAll(threadRecords);
        }
        executor.shutdown();

        long totalMs = System.currentTimeMillis() - totalStart;
        printStats(allRecords, totalMs, totalSent);
        exportCsv(allRecords);
    }

    private List<SendRecord> produceMessages(int threadId, int threadMsgCount, long deadline, boolean timeMode) throws Exception {
        List<SendRecord> records = new ArrayList<>();
        int seq = 0;
        log.info("[thread-{}] started (threadMsgCount={}, timeMode={})", threadId, threadMsgCount, timeMode);

        while (shouldContinue(seq, threadMsgCount, deadline, timeMode)) {
            int end = timeMode ? seq + batchSize : Math.min(seq + batchSize, threadMsgCount);

            if (batchSize == 1) {
                String json = buildMessage(threadId, seq);
                Message<String> message = MessageBuilder.withPayload(json)
                        .setHeader(KafkaHeaders.TOPIC, topic)
                        .setHeader(KafkaHeaders.KEY, "key-" + (seq % 10))
                        .build();

                long sendStart = System.nanoTime();
                RecordMetadata metadata = kafkaTemplate.send(message).get().getRecordMetadata();
                long latencyMs = (System.nanoTime() - sendStart) / 1_000_000;

                records.add(new SendRecord(threadId, seq, latencyMs, metadata.partition(), metadata.offset(), metadata.timestamp()));
                if (seq % 100 == 0) {
                    log.info("[thread-{}] msg={} partition={} offset={} latency={}ms", threadId, seq, metadata.partition(), metadata.offset(), latencyMs);
                }
                seq++;
            } else {
                List<Future<org.springframework.kafka.support.SendResult<String, String>>> futures = new ArrayList<>();
                long batchStart = System.nanoTime();

                for (int j = seq; j < end; j++) {
                    String json = buildMessage(threadId, j);
                    Message<String> message = MessageBuilder.withPayload(json)
                            .setHeader(KafkaHeaders.TOPIC, topic)
                            .setHeader(KafkaHeaders.KEY, "key-" + (j % 10))
                            .build();
                    futures.add(kafkaTemplate.send(message));
                }

                for (int j = 0; j < futures.size(); j++) {
                    RecordMetadata metadata = futures.get(j).get().getRecordMetadata();
                    long latencyMs = (System.nanoTime() - batchStart) / 1_000_000;
                    records.add(new SendRecord(threadId, seq + j, latencyMs, metadata.partition(), metadata.offset(), metadata.timestamp()));
                }
                log.info("[thread-{}] batch [{}-{}] latency={}ms", threadId, seq, seq + futures.size() - 1, (System.nanoTime() - batchStart) / 1_000_000);
                seq += futures.size();
            }
        }
        log.info("[thread-{}] finished, sent {} messages", threadId, seq);
        return records;
    }

    private boolean shouldContinue(int seq, int threadMsgCount, long deadline, boolean timeMode) {
        if (timeMode) return System.currentTimeMillis() < deadline;
        return seq < threadMsgCount;
    }

    private void ensureTopicExists() {
        Map<String, Object> config = kafkaTemplate.getProducerFactory().getConfigurationProperties();
        try (AdminClient admin = AdminClient.create(config)) {
            if (admin.listTopics().names().get().contains(topic)) {
                log.info("Topic '{}' already exists", topic);
                return;
            }
            try {
                NewTopic newTopic = new NewTopic(topic, 6, (short) 3);
                newTopic.configs(Map.of("min.insync.replicas", "2"));
                admin.createTopics(Collections.singleton(newTopic)).all().get();
                log.info("Created topic '{}' (partitions=6, rf=3, min.insync.replicas=2)", topic);
            } catch (Exception e) {
                if (e.getMessage() != null && e.getMessage().contains("min.insync.replicas")) {
                    log.warn("min.insync.replicas not supported (e.g. MSK Express), retrying without it");
                    NewTopic newTopic = new NewTopic(topic, 6, (short) 3);
                    admin.createTopics(Collections.singleton(newTopic)).all().get();
                    log.info("Created topic '{}' (partitions=6, rf=3)", topic);
                } else {
                    throw e;
                }
            }
        } catch (Exception e) {
            log.error("Failed to create topic '{}': {}", topic, e.getMessage());
            throw new RuntimeException("Cannot proceed without topic", e);
        }
    }

    private String buildMessage(int threadId, int seq) throws Exception {
        ObjectNode node = mapper.createObjectNode();
        node.put("thread", threadId);
        node.put("seq", seq);
        node.put("ts", Instant.now().toString());
        node.put("id", UUID.randomUUID().toString());
        node.put("source", "msk-test-spring");

        String base = mapper.writeValueAsString(node);
        if (base.length() < messageSizeBytes) {
            node.put("padding", "x".repeat(messageSizeBytes - base.length()));
        }
        return mapper.writeValueAsString(node);
    }

    private void printStats(List<SendRecord> records, long totalMs, int totalSent) {
        if (records.isEmpty()) return;

        // Per-thread stats
        Map<Integer, List<Long>> byThread = new java.util.TreeMap<>();
        for (SendRecord r : records) {
            byThread.computeIfAbsent(r.threadId, k -> new ArrayList<>()).add(r.latencyMs);
        }
        for (var entry : byThread.entrySet()) {
            List<Long> sorted = entry.getValue().stream().sorted().toList();
            long sum = sorted.stream().mapToLong(Long::longValue).sum();
            log.info("[thread-{}] sent={} avg={}ms p50={}ms p99={}ms",
                    entry.getKey(), sorted.size(),
                    String.format("%.1f", (double) sum / sorted.size()),
                    sorted.get(sorted.size() / 2),
                    sorted.get((int) (sorted.size() * 0.99)));
        }

        // Aggregate stats
        List<Long> sorted = records.stream().map(SendRecord::latencyMs).sorted().toList();
        long sum = sorted.stream().mapToLong(Long::longValue).sum();
        double avg = (double) sum / sorted.size();
        long p50 = sorted.get(sorted.size() / 2);
        long p95 = sorted.get((int) (sorted.size() * 0.95));
        long p99 = sorted.get((int) (sorted.size() * 0.99));
        long min = sorted.get(0);
        long max = sorted.get(sorted.size() - 1);

        log.info("=== RESULTS ===");
        log.info("Total messages: {} (across {} threads)", totalSent, byThread.size());
        log.info("Threads: {}", threads);
        log.info("Batch size: {}", batchSize);
        log.info("Total time: {}ms", totalMs);
        log.info("Throughput: {} msg/s", String.format("%.1f", (double) totalSent / totalMs * 1000));
        log.info("Latency (ms) - avg={} min={} max={} p50={} p95={} p99={}",
                String.format("%.1f", avg), min, max, p50, p95, p99);
    }

    private void exportCsv(List<SendRecord> records) throws Exception {
        String filename = "latency-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")) + ".csv";
        try (PrintWriter pw = new PrintWriter(new FileWriter(filename))) {
            pw.println("thread,seq,latency_ms,partition,offset,timestamp");
            for (SendRecord r : records) {
                pw.printf("%d,%d,%d,%d,%d,%d%n", r.threadId, r.seq, r.latencyMs, r.partition, r.offset, r.timestamp);
            }
        }
        log.info("CSV exported: {}", filename);
    }
}
