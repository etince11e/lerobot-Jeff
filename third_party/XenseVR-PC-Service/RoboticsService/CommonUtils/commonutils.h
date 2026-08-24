// Common utility class for logging and network operations
#ifndef COMMONUTILS_H
#define COMMONUTILS_H

#include <QObject>
#include <QDebug>

#include "CommonUtils_global.h"

#define DEFAULT_LOG_FILE_PATH "log.txt"
#define MAX_LOG_FILE_NUM 30
#define MIN(x,y) ((x)>(y)?(x):(y))


class COMMONUTILSSHARED_EXPORT CommonUtils:public QObject
{
    Q_OBJECT
public:
    CommonUtils();
    ~CommonUtils();

public slots:
    quint64 getThisPoint()
    {
        return (quint64)this;
    }

    static void installLogHandler();
    static QString getLocalIPv4Address();
    static QStringList getLocalIPv4AddressList();
    static bool isOnline();

public:
    static QString m_logPath;

};

#endif // COMMONUTILS_H
