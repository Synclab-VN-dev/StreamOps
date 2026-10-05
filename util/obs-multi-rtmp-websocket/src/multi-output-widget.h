#pragma once

#include "pch.h"
#include <vector>
#include <string>
#include <QListWidget>
#include <QScrollArea>
#include <QVBoxLayout>
#include "push-widget.h"
#include "output-config.h"

class OutputsListWidget : public QListWidget
{
    Q_OBJECT
public:
    using QListWidget::QListWidget;
    QSize sizeHint() const override;
    QSize minimumSizeHint() const override;

protected:
    bool event(QEvent *event) override;

private:
    int ContentHeight() const;
};

class MultiOutputWidget : public QWidget
{
    Q_OBJECT
public:
    MultiOutputWidget(QWidget* parent = nullptr);
    virtual ~MultiOutputWidget();

    std::vector<PushWidget*> GetAllPushWidgets();
    void SaveConfig();
    void LoadConfig();

public slots:
    void RefreshUI();

    // Websocket configuration methods
    bool AddNewTarget(const QString& name, const QString& protocol = "RTMP");
    bool CloneTarget(const QString& sourceId, const QString& newName, const QString& newStreamKey = "");
    bool UpdateTargetName(const QString& targetId, const QString& newName);
    bool UpdateTargetStreamKey(const QString& targetId, const QString& streamKey);
    bool UpdateTargetServiceParam(const QString& targetId, const QString& key, const QString& value);
    bool DeleteTarget(const QString& targetId);
    bool UpdateSyncStart(const QString& targetId, bool syncStart);
    bool UpdateSyncStop(const QString& targetId, bool syncStop);
    PushWidget* FindPushWidgetById(const QString& targetId);

private:
    void DeletePushWidget(const std::string& targetId);
    PushWidget* AddPushWidget(const std::string& targetId);
    void OnOutputMoved(
        const QModelIndex &parent,
        int start,
        int end,
        const QModelIndex &destination,
        int row
    );

    QWidget* container_ = nullptr;
    QVBoxLayout* layout_ = nullptr;
    QScrollArea scroll_;
    OutputsListWidget* outputsContainer_ = nullptr;
};
