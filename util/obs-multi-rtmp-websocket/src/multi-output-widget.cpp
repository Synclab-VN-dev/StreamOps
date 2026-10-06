#include "multi-output-widget.h"
#include "plugin-support.h"
#include "output-config.h"
#include "protocols.h"
#include <QDialog>
#include <QHBoxLayout>
#include <unordered_map>
#include <algorithm>
#include <json.hpp>

QSize OutputsListWidget::sizeHint() const
{
    QSize hint = QListWidget::sizeHint();
    hint.setHeight(ContentHeight());
    return hint;
}

QSize OutputsListWidget::minimumSizeHint() const
{
    return sizeHint();
}

bool OutputsListWidget::event(QEvent *event)
{
    const bool handled = QListWidget::event(event);
    switch (event->type()) {
    case QEvent::FontChange:
    case QEvent::LayoutRequest:
    case QEvent::PolishRequest:
    case QEvent::Show:
    case QEvent::StyleChange:
        updateGeometry();
        break;
    default:
        break;
    }
    return handled;
}

int OutputsListWidget::ContentHeight() const
{
    auto *widget = const_cast<OutputsListWidget *>(this);
    widget->doItemsLayout();
    int totalHeight = frameWidth() * 2;
    const int itemCount = count();
    for (int i = 0; i < itemCount; ++i) {
        totalHeight += sizeHintForRow(i);
    }
    if (itemCount > 1) {
        totalHeight += (itemCount - 1) * spacing();
    }
    return (std::max)(totalHeight, frameWidth() * 2);
}

MultiOutputWidget::MultiOutputWidget(QWidget* parent)
    : QWidget(parent)
{
    setWindowTitle(obs_module_text("Title"));
    container_ = new QWidget(&scroll_);
    layout_ = new QVBoxLayout(container_);
    layout_->setAlignment(Qt::AlignmentFlag::AlignTop);
    layout_->setSizeConstraint(QLayout::SetMinAndMaxSize);

    // init widget
    auto addButton = new QPushButton(obs_module_text("Btn.NewTarget"), container_);
    QObject::connect(addButton, &QPushButton::clicked, [this]() {
        auto& global = GlobalMultiOutputConfig();
        auto newId = GenerateId(global);
        auto target = std::make_shared<OutputTargetConfig>();
        target->id = newId;
        target->protocol = "RTMP";
        global.targets.emplace_back(target);
        auto pushWidget = AddPushWidget(newId);
        if (pushWidget && pushWidget->ShowEditDlg()) {
            SaveConfig();
        } else {
            DeletePushWidget(newId);
        }
    });
    layout_->addWidget(addButton);

    // start all, stop all
    auto allBtnContainer = new QWidget(this);
    auto allBtnLayout = new QHBoxLayout();
    auto startAllButton = new QPushButton(obs_module_text("Btn.StartAll"), allBtnContainer);
    allBtnLayout->addWidget(startAllButton);
    auto stopAllButton = new QPushButton(obs_module_text("Btn.StopAll"), allBtnContainer);
    allBtnLayout->addWidget(stopAllButton);
    allBtnContainer->setLayout(allBtnLayout);
    layout_->addWidget(allBtnContainer);

    QObject::connect(startAllButton, &QPushButton::clicked, [this]() {
        for (auto x : GetAllPushWidgets())
            if (x) x->StartStreaming();
    });
    QObject::connect(stopAllButton, &QPushButton::clicked, [this]() {
        for (auto x : GetAllPushWidgets())
            if (x) x->StopStreaming();
    });

    // load and show outputs
    outputsContainer_ = new OutputsListWidget(container_);
    outputsContainer_->setDragDropMode(QAbstractItemView::InternalMove);
    outputsContainer_->setSelectionMode(QAbstractItemView::SingleSelection);
    outputsContainer_->setDropIndicatorShown(true);
    outputsContainer_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Maximum);
    outputsContainer_->setSizeAdjustPolicy(QAbstractScrollArea::AdjustToContents);
    outputsContainer_->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    outputsContainer_->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    outputsContainer_->setStyleSheet(
        "QListWidget {"
        "   padding: 0px;"
        "   margin: 0px;"
        "   border: none;"
        "   background: transparent;"
        "}"
        "QListWidget::item:selected, QListWidget::item:active {"
        "   border: none;"
        "   background: transparent;"
        "}"
        "QListWidget::item:hover, QListWidget::item:hover:selected, QListWidget::item:hover:active {"
        "   border: none;"
        "   background: rgba(127, 127, 127, 0.1);"
        "   cursor: move;"
        "}"
    );

    LoadConfig();

    connect(
        outputsContainer_->model(),
        &QAbstractItemModel::rowsMoved,
        this,
        &MultiOutputWidget::OnOutputMoved
    );
    layout_->addWidget(outputsContainer_);

    // donate
    if (std::string("\xe5\xa4\x9a\xe8\xb7\xaf\xe6\x8e\xa8\xe6\xb5\x81") == obs_module_text("Title"))
    {
        auto cr = new QWidget(container_);
        auto innerLayout = new QGridLayout(cr);
        innerLayout->setAlignment(Qt::AlignmentFlag::AlignLeft);
        auto label = new QLabel(u8"该插件免费提供，\r\n如您是付费取得，可向商家申请退款\r\n免费领红包或投喂支持插件作者。", cr);
        innerLayout->addWidget(label, 0, 0, 1, 2);
        innerLayout->setColumnStretch(0, 4);
        auto label2 = new QLabel(u8"作者：雷鸣", cr);
        innerLayout->addWidget(label2, 1, 0, 1, 1);
        auto btnFeed = new QPushButton(u8"支持", cr);
        innerLayout->addWidget(btnFeed, 1, 1, 1, 1);
        
        QObject::connect(btnFeed, &QPushButton::clicked, [this]() {
            const char redbagpng[] = 
                "iVBORw0KGgoAAAANSUhEUgAAAJgAAACXAQMAAADTWgC3AAAABlBMVEUAAAD///+l2Z/dAAAAAWJLR0Q"
                "AiAUdSAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAWtJREFUSMe1lk2OgzAMhY1YZJkj5CbkYkggcTG4SY"
                "6QZRaonmcHqs7PYtTaVVWSLxJu7JfnEP/+0H9ZIaKRA0aZz4QJJXuGQFsJO9HU104H1ihuTENl4IS12"
                "YmVcFSa4unJuE2xZV69mOav5XrX6nRgMi6Ii+3Nr9p4k8m7w5OtmOVbzw8ZrOmbxs0Y/ktENMlfnQnx"
                "NweG2vB1ZrZCPoyPfmbwXWSPiz1DvIrHwOHgFQsQtTkrmG6McRvqUu4aGbM28Cm1wRM62HtOP2DwkFF"
                "ypKVoU/dEa8Y9rtaFJLg5EzscoSfBKMWgZ8aY9bj4EQ1jo9GDIR68kKukMCF/6pPWTPW0R9XulVNzpj"
                "6Z5ZzMpOZrzvRElPC49Awx2LOi3k7aP+akhnL1AEMmPYphvtqeGD032TPt5zB2kQBq5Mgo9hrl7lceT"
                "MQsEkD80YH1O9xRw9Vzn/cSQ6Y6EK1JH3nVxvss/GCf3L3/YF97Nxv6vuoIAwAAAABJRU5ErkJggg=="
                ;
            const char alipaypng[] = 
                "iVBORw0KGgoAAAANSUhEUgAAALsAAAC4AQMAAACByg+HAAAABlBMVEUAAAD///+l2Z/dAAAAAWJLR0Q"
                "AiAUdSAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAVtJREFUWMPNmEGugzAMRM0qx+CmIbkpx8gK1zM2/U"
                "L66w4RogqvC5dhxqbm/6/TfgEuwzr8PNwnjhP7pgYNxR1r97XPhUvxjUsPztj0hkJ7O7c4m/V3gCg36"
                "r5Q68uA7SHtaC8BlBbP2T4awFNzEaANOtSt4+EPEciEiKJn2eCZJSIQ5XbU5yFt+HNUfIgBNqFo6Grh"
                "BDxttIQcoL5ICrsTbdAYWgBPIltxK7uVRaeLQToTFRMbb+JoYoAHjsG63UWXtFIQm2w/mV9x9vodUnC"
                "vCWfuiA+oqwaLH7Al8qL/aS4GA9I6zkz/bbFBSsHVKi++Dftg89YC53DDq8iLTJCSVgcq6DlMZGRkzm"
                "pBtW2jRRH3flU3UIIacWBLduv0gxzwltGTaUtOFS4HVSJHnBp35jvAsbJnV/RbewWgtLVyAlODkjZSd"
                "eMrkNfsIwX3awYfuLLEaGKg/OvlAz+wXVruSNSgAAAAAElFTkSuQmCC";
            const char wechatpng[] = 
                "iVBORw0KGgoAAAANSUhEUgAAAK8AAACtAQMAAAD8lL09AAAABlBMVEUAAAD///+l2Z/dAAAAAWJLR0Q"
                "AiAUdSAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAbpJREFUSMe9l0GugzAMRI26yDJHyE3Si1WiEhcrN8"
                "kRWLJA8Z9xaNUv/eUfUIXgqQtn4pkY87+ubv+Cd8O1T3g2y4unzveqxXf3BniUeLKa3XcxrnZr+32zg"
                "iXPDvy0S/C04WYo4jpsKCK97FH2K3DovfqzoJzAX9sgwtFVNS/tvH03mwYPs6zb7PjDrf22lAZT6ugq"
                "wwtaCzLYWLwO13yUUQl3N70yDSTFWOqCJbORsdloLYguxrSNgxyWhl3Z0l2LjWaZUE541qaRFUqM342"
                "5sDTYdY5EZE1KjHU/z25+0UV3yi/GE4LeubHe0V9QYFZjEOhN70QOmp0JocSdGT82Nh+D7nrcQoHkDO"
                "GOcmLnhXil3vAsy5nRWhS9SjGkhmMiddHIMO6580oMu5a0xpAC0aOSOHd0mC+jodjNnhyVqDH1Tj3Ts"
                "0hEm3CGv7dYhDkdQGr0cOJxxquMM02GI44g+tKiqwwZVd4HugjHfOKxeEYvQ9jVOKawzrRnQkQSf4Yz"
                "EeasiWHhwfYNF8WkIscc985pKCaGSzA9S6eGAmpMvRlFzonBLZ6qFp8nyhxSM/IP+3x2arDwc/kHxnM"
                "tm62qBBUAAAAASUVORK5CYII=";

            auto donateWnd = new QDialog();
            donateWnd->setWindowTitle(u8"赞助");
            QTabWidget* tab = new QTabWidget(donateWnd);
            auto redbagQr = new QLabel(donateWnd);
            auto redbagQrBmp = QPixmap::fromImage(QImage::fromData(QByteArray::fromBase64(QByteArray::fromRawData(redbagpng, sizeof(redbagpng) - 1)), "png"));
            redbagQr->setPixmap(redbagQrBmp);
            tab->addTab(redbagQr, u8"支付宝领红包");
            auto aliQr = new QLabel(donateWnd);
            auto aliQrBmp = QPixmap::fromImage(QImage::fromData(QByteArray::fromBase64(QByteArray::fromRawData(alipaypng, sizeof(alipaypng) - 1)), "png"));
            aliQr->setPixmap(aliQrBmp);
            tab->addTab(aliQr, u8"支付宝打赏");
            auto weQr = new QLabel(donateWnd);
            auto weQrBmp = QPixmap::fromImage(QImage::fromData(QByteArray::fromBase64(QByteArray::fromRawData(wechatpng, sizeof(wechatpng) - 1)), "png"));
            weQr->setPixmap(weQrBmp);
            tab->addTab(weQr, u8"微信打赏");
            auto layout = new QGridLayout();
            layout->setRowStretch(0, 1);
            layout->setColumnStretch(0, 1);
            layout->addWidget(new QLabel(u8"打赏并非购买，不提供退款。", donateWnd), 0, 0);
            layout->addWidget(tab, 1, 0);
            donateWnd->setLayout(layout);
            donateWnd->setMinimumWidth(360);
            donateWnd->exec();
        });
        layout_->addWidget(cr);
    }
    else
    {
        auto label = new QLabel(u8"<p>This plugin is provided for free. <br>Author: SoraYuki (<a href=\"https://paypal.me/sorayuki0\">donate</a>) </p>", container_);
        label->setTextFormat(Qt::RichText);
        label->setTextInteractionFlags(Qt::TextBrowserInteraction);
        label->setOpenExternalLinks(true);
        layout_->addWidget(label);
    }

    scroll_.setWidgetResizable(true);
    scroll_.setWidget(container_);
    auto fullLayout = new QGridLayout(this);
    fullLayout->setContentsMargins(0, 0, 0, 0);
    fullLayout->setRowStretch(0, 1);
    fullLayout->setColumnStretch(0, 1);
    fullLayout->addWidget(&scroll_, 0, 0);
}

MultiOutputWidget::~MultiOutputWidget()
{
}

std::vector<PushWidget*> MultiOutputWidget::GetAllPushWidgets()
{
    std::vector<PushWidget*> result;
    if (!outputsContainer_) return result;

    for (int row = 0; row < outputsContainer_->count(); ++row) {
        auto item = outputsContainer_->item(row);
        if (!item) continue;
        auto widget = outputsContainer_->itemWidget(item);
        auto pushWidget = dynamic_cast<PushWidget*>(widget);
        if (pushWidget) {
            result.push_back(pushWidget);
        }
    }
    return result;
}

void MultiOutputWidget::SaveConfig()
{
    SaveMultiOutputConfig();
}

void MultiOutputWidget::RefreshUI()
{
    LoadConfig();
}

void MultiOutputWidget::OnOutputMoved(
    const QModelIndex &parent,
    int start,
    int end,
    const QModelIndex &destination,
    int row
)
{
    // QListWidget uses a single root parent for internal move operations.
    if (parent != destination) {
        return;
    }
    const int count = outputsContainer_->count();
    if (count <= 0 || start < 0 || end < start || row < 0 || row > count) {
        return;
    }

    auto &targets = GlobalMultiOutputConfig().targets;
    std::unordered_map<std::string, OutputTargetConfigPtr> targetById;
    targetById.reserve(targets.size());
    for (auto &target : targets) {
        if (target) {
            targetById.emplace(target->id, target);
        }
    }

    std::remove_reference_t<decltype(targets)> reordered;
    for (int i = 0; i < count; ++i) {
        auto item = outputsContainer_->item(i);
        if (!item) continue;
        auto id = item->data(Qt::UserRole).toString().toStdString();
        auto it = targetById.find(id);
        if (it == targetById.end()) continue;
        reordered.emplace_back(it->second);
        targetById.erase(it);
    }

    // Keep unmatched items in their previous order to avoid accidental loss.
    if (!targetById.empty()) {
        for (auto &target : targets) {
            if (!target) continue;
            auto it = targetById.find(target->id);
            if (it == targetById.end()) continue;
            reordered.emplace_back(it->second);
            targetById.erase(it);
        }
    }

    targets.swap(reordered);
    SaveConfig();
    outputsContainer_->clearSelection();
}

void MultiOutputWidget::LoadConfig()
{
    if (!outputsContainer_) return;
    outputsContainer_->clear();
    GlobalMultiOutputConfig() = {};
    if (!LoadMultiOutputConfig()) {
        return;
    }
    for (auto x : GlobalMultiOutputConfig().targets)
    {
        if (x) AddPushWidget(x->id);
    }
}

void MultiOutputWidget::DeletePushWidget(const std::string& targetId)
{
    // Delete from model
    auto outputTargets = &(GlobalMultiOutputConfig().targets);
    auto currentTarget = std::find_if(outputTargets->begin(), outputTargets->end(),
        [&targetId](const auto& x) { return x && x->id == targetId; });
    if (currentTarget != outputTargets->end()) {
        outputTargets->erase(currentTarget);
    }

    // Delete from List View
    const QString id = QString::fromStdString(targetId);
    for (auto listItem : outputsContainer_->findItems("", Qt::MatchContains)) {
        if (listItem->data(Qt::UserRole).toString() != id) {
            continue;
        }
        int row = outputsContainer_->row(listItem);
        auto removedItem = outputsContainer_->takeItem(row);
        auto pushWidget = outputsContainer_->itemWidget(removedItem);
        delete removedItem;
        if (pushWidget) {
            pushWidget->deleteLater();
        }
    }
}

PushWidget* MultiOutputWidget::AddPushWidget(const std::string& targetId)
{
    auto pushWidget = createPushWidget(targetId, outputsContainer_->viewport());
    if (!pushWidget) return nullptr;

    QListWidgetItem* listItem = new QListWidgetItem();
    listItem->setData(Qt::UserRole, QString::fromStdString(targetId));
    listItem->setSizeHint(pushWidget->sizeHint());
    outputsContainer_->addItem(listItem);
    outputsContainer_->setItemWidget(listItem, pushWidget);

    auto delBtn = pushWidget->GetDeleteButton();
    if (delBtn) {
        QObject::connect(delBtn, &QPushButton::clicked, [this, targetId]() {
            auto msgbox = new QMessageBox(
                QMessageBox::Icon::Question,
                obs_module_text("Question.Title"),
                obs_module_text("Question.Delete"),
                QMessageBox::Yes | QMessageBox::No,
                this
            );
            if (msgbox->exec() != QMessageBox::Yes) {
                return;
            }
            DeletePushWidget(targetId);
            SaveConfig();
        });
    }

    return pushWidget;
}

// Websocket configuration methods
bool MultiOutputWidget::AddNewTarget(const QString& name, const QString& protocol)
{
    if (name.isEmpty()) {
        blog(LOG_WARNING, TAG "AddNewTarget failed: Empty name provided");
        return false;
    }

    QString validProtocol = protocol.trimmed().toUpper();
    if (validProtocol.isEmpty()) {
        validProtocol = "RTMP";
    }

    auto& global = GlobalMultiOutputConfig();
    auto newId = GenerateId(global);
    auto target = std::make_shared<OutputTargetConfig>();
    target->id = newId;
    target->name = name.toStdString();
    target->protocol = validProtocol.toStdString();
    global.targets.emplace_back(target);

    AddPushWidget(newId);
    SaveConfig();

    blog(LOG_INFO, TAG "Added new target via WebSocket: %s (Protocol: %s, ID: %s)",
         name.toUtf8().constData(), validProtocol.toUtf8().constData(), newId.c_str());
    return true;
}

bool MultiOutputWidget::CloneTarget(const QString& sourceId, const QString& newName, const QString& newStreamKey)
{
    auto& global = GlobalMultiOutputConfig();
    std::string srcId = sourceId.toStdString();
    auto it = std::find_if(global.targets.begin(), global.targets.end(),
        [&srcId](const auto& t) { return t && t->id == srcId; });
    if (it == global.targets.end() || !(*it)) {
        blog(LOG_WARNING, TAG "CloneTarget failed: Source target %s not found", sourceId.toUtf8().constData());
        return false;
    }

    auto sourceConfig = *it;
    auto newTarget = std::make_shared<OutputTargetConfig>(*sourceConfig);
    newTarget->id = GenerateId(global);
    if (!newName.isEmpty()) {
        newTarget->name = newName.toStdString();
    } else {
        newTarget->name = sourceConfig->name + " (Copy)";
    }

    if (!newStreamKey.isEmpty()) {
        try {
            auto serviceParams = nlohmann::json::parse(newTarget->serviceParam.dump());
            if (newTarget->protocol == "SRT" || newTarget->protocol == "srt") {
                serviceParams["streamid"] = newStreamKey.toStdString();
            } else {
                serviceParams["key"] = newStreamKey.toStdString();
            }
            newTarget->serviceParam = serviceParams;
        } catch (const std::exception& e) {
            blog(LOG_WARNING, TAG "Failed to update stream key during clone: %s", e.what());
        }
    }

    global.targets.emplace_back(newTarget);
    AddPushWidget(newTarget->id);
    SaveConfig();
    return true;
}

bool MultiOutputWidget::UpdateTargetName(const QString& targetId, const QString& newName)
{
    if (newName.isEmpty()) {
        blog(LOG_WARNING, TAG "UpdateTargetName failed: Empty name provided for target %s", targetId.toUtf8().constData());
        return false;
    }

    auto& global = GlobalMultiOutputConfig();
    std::string id = targetId.toStdString();
    for (auto& target : global.targets) {
        if (target && target->id == id) {
            target->name = newName.toStdString();
            SaveConfig();
            auto pw = FindPushWidgetById(targetId);
            if (pw) pw->UpdateUI();
            blog(LOG_INFO, TAG "Updated target name: %s -> %s", id.c_str(), newName.toUtf8().constData());
            return true;
        }
    }
    blog(LOG_WARNING, TAG "UpdateTargetName failed: Target %s not found", targetId.toUtf8().constData());
    return false;
}

bool MultiOutputWidget::UpdateTargetStreamKey(const QString& targetId, const QString& streamKey)
{
    if (streamKey.isEmpty()) {
        blog(LOG_WARNING, TAG "UpdateStreamKey failed: Empty stream key for target %s", targetId.toUtf8().constData());
        return false;
    }

    auto& global = GlobalMultiOutputConfig();
    std::string id = targetId.toStdString();
    for (auto& target : global.targets) {
        if (target && target->id == id) {
            try {
                auto serviceParams = nlohmann::json::parse(target->serviceParam.dump());
                std::string param_name = (target->protocol == "SRT" || target->protocol == "srt") ? "streamid" : "key";
                serviceParams[param_name] = streamKey.toStdString();
                target->serviceParam = serviceParams;
                SaveConfig();
                auto pw = FindPushWidgetById(targetId);
                if (pw) pw->UpdateUI();
                blog(LOG_INFO, TAG "Updated stream key for target %s (%s)", targetId.toUtf8().constData(), target->protocol.c_str());
                return true;
            } catch (const std::exception& e) {
                blog(LOG_WARNING, TAG "Failed to update stream key for %s: %s", targetId.toUtf8().constData(), e.what());
                return false;
            }
        }
    }
    blog(LOG_WARNING, TAG "UpdateStreamKey failed: Target not found %s", targetId.toUtf8().constData());
    return false;
}

bool MultiOutputWidget::UpdateTargetServiceParam(const QString& targetId, const QString& key, const QString& value)
{
    if (key.isEmpty() || value.isEmpty()) {
        blog(LOG_WARNING, TAG "UpdateServiceParam failed: Empty key or value for target %s", targetId.toUtf8().constData());
        return false;
    }

    auto& global = GlobalMultiOutputConfig();
    std::string id = targetId.toStdString();
    for (auto& target : global.targets) {
        if (target && target->id == id) {
            try {
                auto serviceParams = nlohmann::json::parse(target->serviceParam.dump());
                std::string keyStr = key.toStdString();
                std::string valueStr = value.toStdString();

                if (valueStr == "true" || valueStr == "false") {
                    serviceParams[keyStr] = (valueStr == "true");
                } else {
                    serviceParams[keyStr] = valueStr;
                }

                target->serviceParam = serviceParams;
                SaveConfig();
                auto pw = FindPushWidgetById(targetId);
                if (pw) pw->UpdateUI();
                // Service parameters may contain credentials (stream keys/tokens).
                // Log the field name only; never echo the value.
                blog(LOG_INFO, TAG "Updated service param for target %s: %s = <redacted>",
                     targetId.toUtf8().constData(), key.toUtf8().constData());
                return true;
            } catch (const std::exception& e) {
                blog(LOG_WARNING, TAG "Failed to update service param for %s: %s", targetId.toUtf8().constData(), e.what());
                return false;
            }
        }
    }
    blog(LOG_WARNING, TAG "UpdateServiceParam failed: Target not found %s", targetId.toUtf8().constData());
    return false;
}

bool MultiOutputWidget::DeleteTarget(const QString& targetId)
{
    DeletePushWidget(targetId.toStdString());
    SaveConfig();
    blog(LOG_INFO, TAG "Deleted target via WebSocket: %s", targetId.toUtf8().constData());
    return true;
}

bool MultiOutputWidget::UpdateSyncStart(const QString& targetId, bool syncStart)
{
    auto& global = GlobalMultiOutputConfig();
    std::string id = targetId.toStdString();
    for (auto& target : global.targets) {
        if (target && target->id == id) {
            target->syncStart = syncStart;
            SaveConfig();
            auto pw = FindPushWidgetById(targetId);
            if (pw) pw->UpdateUI();
            blog(LOG_INFO, TAG "Updated sync start for %s: %s", targetId.toUtf8().constData(), syncStart ? "true" : "false");
            return true;
        }
    }
    blog(LOG_WARNING, TAG "UpdateSyncStart failed: Target not found %s", targetId.toUtf8().constData());
    return false;
}

bool MultiOutputWidget::UpdateSyncStop(const QString& targetId, bool syncStop)
{
    auto& global = GlobalMultiOutputConfig();
    std::string id = targetId.toStdString();
    for (auto& target : global.targets) {
        if (target && target->id == id) {
            target->syncStop = syncStop;
            SaveConfig();
            auto pw = FindPushWidgetById(targetId);
            if (pw) pw->UpdateUI();
            blog(LOG_INFO, TAG "Updated sync stop for %s: %s", targetId.toUtf8().constData(), syncStop ? "true" : "false");
            return true;
        }
    }
    blog(LOG_WARNING, TAG "UpdateSyncStop failed: Target not found %s", targetId.toUtf8().constData());
    return false;
}

PushWidget* MultiOutputWidget::FindPushWidgetById(const QString& targetId)
{
    for (auto* widget : GetAllPushWidgets()) {
        if (widget && widget->GetTargetId() == targetId) {
            return widget;
        }
    }
    return nullptr;
}
